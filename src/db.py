"""Capa de datos SQLite.

Guardamos las métricas en **formato tidy/largo** (una fila por
publicación + métrica + momento de captura) en vez de una tabla ancha de
columnas fijas. Dos razones:

  1. Resiliencia: si Meta agrega/saca métricas entre versiones, no hay que
     migrar el esquema — simplemente aparecen (o no) filas nuevas.
  2. Histórico: cada corrida de `fetch` guarda un snapshot con su timestamp,
     así construimos series temporales que la API no ofrece hacia atrás
     (clave para las historias, que expiran a las 24 h).

Tablas:
  media              -> metadatos + caption + tema de cada publicación
  metrics            -> valores (largo) con captured_at
  account_snapshots  -> seguidores/seguidos en el tiempo
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Mapping

from config import settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS media (
    media_id            TEXT PRIMARY KEY,
    caption             TEXT,
    media_type          TEXT,           -- IMAGE | VIDEO | CAROUSEL_ALBUM
    media_product_type  TEXT,           -- FEED | REELS | STORY
    timestamp           TEXT,           -- fecha de publicación (ISO, de la API)
    permalink           TEXT,
    thumbnail_url       TEXT,
    media_url           TEXT,
    like_count          INTEGER,
    comments_count      INTEGER,
    topic               TEXT,           -- tema asignado por IA
    topic_manual        TEXT,           -- override manual (tiene prioridad)
    first_seen          TEXT,           -- primera vez que lo capturamos
    last_seen           TEXT            -- última vez que lo capturamos
);

CREATE TABLE IF NOT EXISTS metrics (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id     TEXT NOT NULL,
    metric_name  TEXT NOT NULL,
    value        REAL,
    captured_at  TEXT NOT NULL,
    FOREIGN KEY (media_id) REFERENCES media(media_id)
);

CREATE INDEX IF NOT EXISTS idx_metrics_media   ON metrics(media_id);
CREATE INDEX IF NOT EXISTS idx_metrics_name    ON metrics(metric_name);
CREATE INDEX IF NOT EXISTS idx_metrics_capture ON metrics(captured_at);

CREATE TABLE IF NOT EXISTS account_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at     TEXT NOT NULL,
    username        TEXT,
    followers_count INTEGER,
    follows_count   INTEGER,
    media_count     INTEGER
);
"""


def now_iso() -> str:
    """Timestamp UTC en ISO-8601 (para captured_at)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Conexión SQLite con row_factory y foreign keys activadas."""
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    """Crea las tablas si no existen (idempotente)."""
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)


def upsert_media(conn: sqlite3.Connection, media: Mapping, captured_at: str) -> None:
    """Inserta o actualiza los metadatos de una publicación.

    Preserva `topic_manual` (el override del usuario) y `first_seen`: solo se
    setean si la fila es nueva; en updates se respetan los valores existentes.
    """
    conn.execute(
        """
        INSERT INTO media (
            media_id, caption, media_type, media_product_type, timestamp,
            permalink, thumbnail_url, media_url, like_count, comments_count,
            first_seen, last_seen
        ) VALUES (
            :media_id, :caption, :media_type, :media_product_type, :timestamp,
            :permalink, :thumbnail_url, :media_url, :like_count, :comments_count,
            :captured_at, :captured_at
        )
        ON CONFLICT(media_id) DO UPDATE SET
            caption        = excluded.caption,
            media_type     = excluded.media_type,
            media_product_type = excluded.media_product_type,
            timestamp      = excluded.timestamp,
            permalink      = excluded.permalink,
            thumbnail_url  = excluded.thumbnail_url,
            media_url      = excluded.media_url,
            like_count     = excluded.like_count,
            comments_count = excluded.comments_count,
            last_seen      = excluded.last_seen
        """,
        {
            "media_id": media.get("id"),
            "caption": media.get("caption"),
            "media_type": media.get("media_type"),
            "media_product_type": media.get("media_product_type"),
            "timestamp": media.get("timestamp"),
            "permalink": media.get("permalink"),
            "thumbnail_url": media.get("thumbnail_url"),
            "media_url": media.get("media_url"),
            "like_count": media.get("like_count"),
            "comments_count": media.get("comments_count"),
            "captured_at": captured_at,
        },
    )


def insert_metrics(
    conn: sqlite3.Connection,
    media_id: str,
    metrics: Mapping[str, float],
    captured_at: str,
) -> int:
    """Inserta un snapshot de métricas (formato largo). Devuelve cuántas filas."""
    filas = [(media_id, name, value, captured_at) for name, value in metrics.items()]
    if not filas:
        return 0
    conn.executemany(
        "INSERT INTO metrics (media_id, metric_name, value, captured_at) "
        "VALUES (?, ?, ?, ?)",
        filas,
    )
    return len(filas)


def insert_account_snapshot(conn: sqlite3.Connection, account: Mapping, captured_at: str) -> None:
    """Guarda un snapshot de los contadores de la cuenta."""
    conn.execute(
        "INSERT INTO account_snapshots "
        "(captured_at, username, followers_count, follows_count, media_count) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            captured_at,
            account.get("username"),
            account.get("followers_count"),
            account.get("follows_count"),
            account.get("media_count"),
        ),
    )


def set_topic(conn: sqlite3.Connection, media_id: str, *, auto: str | None = None,
              manual: str | None = None) -> None:
    """Asigna el tema de una publicación (IA en `auto`, override en `manual`)."""
    if auto is not None:
        conn.execute("UPDATE media SET topic = ? WHERE media_id = ?", (auto, media_id))
    if manual is not None:
        conn.execute("UPDATE media SET topic_manual = ? WHERE media_id = ?", (manual, media_id))
