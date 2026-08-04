"""Motor de análisis (pandas).

Lee la base SQLite y arma un DataFrame "ancho" (una fila por publicación con el
valor más reciente de cada métrica) sobre el que operan las agregaciones que
consume el dashboard: por formato, por tema, rankings, horarios y minería de hooks.

El foco está en **guardados (saved) y compartidos (shares)**: son las señales
más fuertes de valor real para el algoritmo y las más accionables para un
consultor que quiere que lo descubran.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from src.db import get_connection, init_db

# Métricas que nos interesan para el análisis (las que existan aparecen).
KEY_METRICS = [
    "reach", "views", "likes", "comments", "saved", "shares",
    "total_interactions", "replies", "profile_visits", "follows",
]

# Etiquetas legibles de formato a partir de media_product_type + media_type.
FORMAT_LABELS = {
    "REELS": "Reel",
    "STORY": "Historia",
}


def _latest_metrics_sql() -> str:
    """El valor más reciente de cada (media_id, metric_name)."""
    return """
    SELECT m.media_id, m.metric_name, m.value
    FROM metrics m
    JOIN (
        SELECT media_id, metric_name, MAX(captured_at) AS mx
        FROM metrics GROUP BY media_id, metric_name
    ) t ON m.media_id = t.media_id
       AND m.metric_name = t.metric_name
       AND m.captured_at = t.mx
    """


def build_dataset(db_path: Path | None = None) -> pd.DataFrame:
    """DataFrame ancho: una fila por publicación con metadatos + últimas métricas.

    Columnas añadidas: `formato`, `tema` (efectivo), `publicado` (datetime),
    `dia_semana`, `hora`, `hook` (primera línea del caption) y
    `engagement_rate`. Devuelve DataFrame vacío si no hay datos aún.
    """
    init_db(db_path)  # garantiza que las tablas existan (dashboard antes del 1er fetch)
    with get_connection(db_path) as conn:
        media = pd.read_sql_query("SELECT * FROM media", conn)
        metrics = pd.read_sql_query(_latest_metrics_sql(), conn)

    if media.empty:
        return media

    # Pivot de métricas (largo -> ancho).
    if not metrics.empty:
        wide = metrics.pivot_table(
            index="media_id", columns="metric_name", values="value", aggfunc="last"
        ).reset_index()
    else:
        wide = pd.DataFrame({"media_id": media["media_id"]})

    df = media.merge(wide, on="media_id", how="left")

    # Garantiza que existan las columnas clave (aunque falten en los datos).
    for m in KEY_METRICS:
        if m not in df.columns:
            df[m] = pd.NA

    # Tema efectivo: el override manual manda sobre el automático.
    df["tema"] = df["topic_manual"].fillna(df["topic"]).fillna("sin_etiquetar")

    # Formato legible.
    df["formato"] = df.apply(_formato, axis=1)

    # Fecha de publicación y derivados temporales.
    df["publicado"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    dias = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    df["dia_semana"] = df["publicado"].dt.dayofweek.map(lambda i: dias[i] if pd.notna(i) else None)
    df["hora"] = df["publicado"].dt.hour

    # Hook = primera línea no vacía del caption.
    df["hook"] = df["caption"].apply(_primera_linea)

    # Engagement rate = interacciones / alcance (cuando hay alcance).
    interacciones = df["total_interactions"]
    faltan = interacciones.isna()
    if faltan.any():  # fallback: sumar componentes si no vino total_interactions
        componentes = df[["likes", "comments", "saved", "shares"]].fillna(0).sum(axis=1)
        interacciones = interacciones.fillna(componentes)
    df["interacciones"] = interacciones
    df["engagement_rate"] = (interacciones / df["reach"]).where(df["reach"] > 0)

    return df


def _formato(row: pd.Series) -> str:
    product = (row.get("media_product_type") or "").upper()
    if product in FORMAT_LABELS:
        return FORMAT_LABELS[product]
    mtype = (row.get("media_type") or "").upper()
    if mtype == "CAROUSEL_ALBUM":
        return "Carrusel"
    if mtype == "VIDEO":
        return "Video"
    if mtype == "IMAGE":
        return "Foto"
    return product or "Otro"


def _primera_linea(caption: object) -> str:
    if not isinstance(caption, str) or not caption.strip():
        return ""
    for linea in caption.splitlines():
        if linea.strip():
            return linea.strip()
    return ""


# ── Agregaciones ─────────────────────────────────────────────────────────────
def by_format(df: pd.DataFrame) -> pd.DataFrame:
    """Rendimiento promedio por formato."""
    if df.empty:
        return df
    return _agg_group(df, "formato")


def by_topic(df: pd.DataFrame) -> pd.DataFrame:
    """Rendimiento promedio por tema."""
    if df.empty:
        return df
    return _agg_group(df, "tema")


def _agg_group(df: pd.DataFrame, col: str) -> pd.DataFrame:
    presentes = [m for m in ["reach", "views", "saved", "shares", "interacciones"]
                 if m in df.columns]
    g = df.groupby(col).agg(
        publicaciones=("media_id", "count"),
        **{m: (m, "mean") for m in presentes},
        engagement_rate=("engagement_rate", "mean"),
    ).reset_index()
    return g.sort_values("saved", ascending=False) if "saved" in g.columns else g


def ranking(df: pd.DataFrame, metric: str = "saved", n: int = 10,
            ascending: bool = False) -> pd.DataFrame:
    """Top/bottom publicaciones por una métrica."""
    if df.empty or metric not in df.columns:
        return pd.DataFrame()
    cols = ["publicado", "formato", "tema", "hook", metric, "permalink"]
    cols = [c for c in cols if c in df.columns]
    return df.dropna(subset=[metric]).sort_values(metric, ascending=ascending).head(n)[cols]


def timing(df: pd.DataFrame, metric: str = "reach") -> pd.DataFrame:
    """Matriz día-de-semana × hora con el promedio de una métrica."""
    if df.empty or metric not in df.columns:
        return pd.DataFrame()
    orden = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    tabla = df.pivot_table(index="dia_semana", columns="hora", values=metric, aggfunc="mean")
    return tabla.reindex([d for d in orden if d in tabla.index])


def mine_hooks(df: pd.DataFrame, metric: str = "saved", n: int = 15) -> pd.DataFrame:
    """Primeras líneas (hooks) de las publicaciones que más rindieron."""
    if df.empty or metric not in df.columns:
        return pd.DataFrame()
    d = df[df["hook"].str.len() > 0].dropna(subset=[metric])
    cols = ["hook", "tema", "formato", metric]
    return d.sort_values(metric, ascending=False).head(n)[cols]


def followers_series(db_path: Path | None = None) -> pd.DataFrame:
    """Evolución de seguidores a partir de los snapshots de cuenta."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        df = pd.read_sql_query(
            "SELECT captured_at, followers_count, follows_count, media_count "
            "FROM account_snapshots ORDER BY captured_at",
            conn,
        )
    if not df.empty:
        df["captured_at"] = pd.to_datetime(df["captured_at"], errors="coerce", utc=True)
    return df
