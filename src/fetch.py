"""Orquestación: captura un snapshot completo de métricas.

    python -m src.fetch                # todas las publicaciones
    python -m src.fetch --limit 30     # solo las 30 más recientes
    python -m src.fetch --no-stories   # omite historias activas

Es idempotente: los metadatos se actualizan (upsert) y cada corrida agrega un
snapshot nuevo de métricas con su timestamp, construyendo el histórico.

Pensado para correr a mano ahora y, más adelante, con cron en el VPS (a diario,
para capturar historias antes de que expiren a las 24 h).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

from config import enable_utf8_console, settings
from src.db import (
    get_connection,
    init_db,
    insert_account_snapshot,
    insert_metrics,
    now_iso,
    upsert_media,
)
from src.ig_client import InstagramAPIError, InstagramClient


def _cache_thumb(media_id: str, item: dict, thumbs_dir: Path) -> None:
    """Descarga la MINIATURA del post a data/thumbs/{id}.jpg (una sola vez).

    Nunca descarga el video: usa thumbnail_url (reels/video) o media_url solo si
    es IMAGE. Las URLs de la API expiran, por eso las guardamos localmente.
    """
    dest = thumbs_dir / f"{media_id}.jpg"
    if dest.exists():
        return
    url = item.get("thumbnail_url")
    if not url and (item.get("media_type") or "").upper() == "IMAGE":
        url = item.get("media_url")
    if not url:
        return
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 200 and r.content:
            dest.write_bytes(r.content)
    except requests.RequestException:
        pass


def run(limit: int | None = None, include_stories: bool = True) -> None:
    settings.require("access_token")  # user_id es opcional (cae a "me")

    client = InstagramClient()
    captured_at = now_iso()
    init_db()

    print(f"[fetch] Snapshot {captured_at}")

    # ── Cuenta ────────────────────────────────────────────────────────────────
    try:
        account = client.get_account()
    except InstagramAPIError as exc:
        print(f"[fetch] ERROR al leer la cuenta: {exc}", file=sys.stderr)
        raise SystemExit(1)

    print(f"[fetch] Cuenta @{account.get('username')} — "
          f"{account.get('followers_count')} seguidores, "
          f"{account.get('media_count')} publicaciones")

    # ── Publicaciones del feed (reels, carruseles, fotos, videos) ─────────────
    media = client.get_media(limit=limit)
    print(f"[fetch] {len(media)} publicaciones a procesar…")

    if include_stories:
        try:
            stories = client.get_stories()
            if stories:
                print(f"[fetch] + {len(stories)} historias activas")
            media = media + stories
        except InstagramAPIError as exc:
            print(f"[fetch] (aviso) no se pudieron leer historias: {exc}")

    # ── Persistencia ──────────────────────────────────────────────────────────
    n_media = 0
    n_metrics = 0
    con_error: list[str] = []
    thumbs_dir = settings.db_path.parent / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    with get_connection() as conn:
        insert_account_snapshot(conn, account, captured_at)

        for item in media:
            media_id = item.get("id")
            product = (item.get("media_product_type") or "FEED").upper()
            upsert_media(conn, item, captured_at)
            _cache_thumb(media_id, item, thumbs_dir)
            n_media += 1

            try:
                insights = client.get_media_insights(media_id, product)
                n_metrics += insert_metrics(conn, media_id, insights, captured_at)
            except InstagramAPIError as exc:
                con_error.append(f"{media_id} ({product}): {exc}")

            if n_media % 10 == 0:
                print(f"[fetch]   … {n_media}/{len(media)}")

    print(f"[fetch] Listo: {n_media} publicaciones, {n_metrics} métricas guardadas.")
    if con_error:
        print(f"[fetch] {len(con_error)} publicaciones sin insights "
              f"(normal en fotos viejas o contenido sin permiso de insights):")
        for e in con_error[:5]:
            print(f"          - {e}")

    # Auto-etiquetar lo nuevo. Usa el LLM si hay API key (más preciso), y si no
    # cae al clasificador NLP local. No rompe el fetch si algo falla.
    try:
        if settings.anthropic_api_key:
            from src import tagging
            tagging.tag_pending()
        else:
            from src import autotag
            autotag.train_and_tag()
    except Exception as exc:  # noqa: BLE001
        print(f"[fetch] (aviso) auto-etiquetado omitido: {exc}")

    print(f"[fetch] Base: {settings.db_path}")


def main() -> None:
    enable_utf8_console()
    parser = argparse.ArgumentParser(description="Captura un snapshot de métricas de Instagram.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Máximo de publicaciones a procesar (default: todas).")
    parser.add_argument("--no-stories", action="store_true",
                        help="No capturar historias activas.")
    args = parser.parse_args()
    run(limit=args.limit, include_stories=not args.no_stories)


if __name__ == "__main__":
    main()
