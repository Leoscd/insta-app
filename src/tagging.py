"""Etiquetado de tema por publicación.

Instagram no clasifica el contenido por tema; lo hacemos nosotros para poder
cruzar *tema × rendimiento* en el dashboard. La clasificación es asistida por la
API de Claude (sobre el caption) y siempre admite corrección manual desde el
dashboard (columna `topic_manual`, que tiene prioridad).

Si no hay ANTHROPIC_API_KEY configurada, el etiquetado por IA se desactiva y
queda todo listo para etiquetar a mano.

    python -m src.tagging          # etiqueta las publicaciones sin tema
    python -m src.tagging --all    # reclasifica todas (ignora lo ya etiquetado)
"""
from __future__ import annotations

import argparse
import json

from config import enable_utf8_console, settings
from src.db import get_connection, set_topic

# Taxonomía basada en el contenido REAL de @soy.leo_ai (derivada de leer sus 154
# publicaciones). Editable: agregá/sacá temas según evolucione el contenido.
TAXONOMY = [
    "dolor_tiempo",     # dolor de tareas manuales/horas perdidas -> IA libera tiempo
    "mito_ia",          # reencuadres/desmitificar ("no te reemplaza", "no es solo renders")
    "herramienta_demo", # demo de herramienta/sistema/cómo hacer (MCP, Skills, calculadoras, apps)
    "posicionamiento",  # negocio/precios/valor/diferenciación (cobrar por valor, vender proceso)
    "motivacional",     # mindset/identidad/adaptarse/disciplina
    "caso_exito",       # resultados de alumnos/comunidad, testimonios
    "evento",           # charlas/eventos/hitos/agradecimientos (EXPOCON, Fórum)
    "dato_estadistica", # posts que arrancan con una estadística (91%, 73%, 70%)
    "otro",             # no encaja / caption vacío
]

_PROMPT = """Sos un clasificador de contenido de Instagram para un consultor de IA aplicada a arquitectura.
Clasificá cada publicación en EXACTAMENTE una de estas categorías:
{taxonomy}

Devolvé SOLO un objeto JSON válido {{"<media_id>": "<categoria>", ...}} sin texto adicional.
Si un caption está vacío o es ambiguo, usá "otro".

Publicaciones:
{items}"""


def _anthropic_available() -> bool:
    return bool(settings.anthropic_api_key)


def classify_captions(items: list[tuple[str, str]]) -> dict[str, str]:
    """Clasifica [(media_id, caption)] -> {media_id: tema} vía la API de Claude.

    Devuelve {} si no hay API key o si la respuesta no se puede parsear.
    """
    if not items or not _anthropic_available():
        return {}

    try:
        import anthropic
    except ImportError:
        print("[tagging] Falta el paquete 'anthropic' (pip install anthropic).")
        return {}

    listado = "\n".join(
        f'- media_id {mid}: "{(cap or "").strip()[:500]}"' for mid, cap in items
    )
    prompt = _PROMPT.format(taxonomy=", ".join(TAXONOMY), items=listado)

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        resp = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:  # noqa: BLE001 — la API puede fallar por red/cuota
        print(f"[tagging] Error llamando a la API de Claude: {exc}")
        return {}

    texto = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    return _parse_json_mapping(texto)


def _parse_json_mapping(texto: str) -> dict[str, str]:
    """Extrae el objeto JSON de la respuesta, tolerando texto/backticks alrededor."""
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio == -1 or fin == -1:
        return {}
    try:
        data = json.loads(texto[inicio : fin + 1])
    except json.JSONDecodeError:
        return {}
    # Normaliza: solo categorías válidas.
    return {str(k): (v if v in TAXONOMY else "otro") for k, v in data.items()}


def tag_pending(reclassify_all: bool = False, batch_size: int = 25) -> int:
    """Etiqueta las publicaciones sin tema. Devuelve cuántas etiquetó."""
    if not _anthropic_available():
        print("[tagging] Sin ANTHROPIC_API_KEY: etiquetá manualmente desde el dashboard.")
        return 0

    with get_connection() as conn:
        if reclassify_all:
            rows = conn.execute(
                "SELECT media_id, caption FROM media WHERE topic_manual IS NULL"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT media_id, caption FROM media "
                "WHERE topic IS NULL AND topic_manual IS NULL"
            ).fetchall()

        pendientes = [(r["media_id"], r["caption"]) for r in rows]
        if not pendientes:
            print("[tagging] No hay publicaciones pendientes de etiquetar.")
            return 0

        total = 0
        for i in range(0, len(pendientes), batch_size):
            lote = pendientes[i : i + batch_size]
            mapping = classify_captions(lote)
            for media_id, tema in mapping.items():
                set_topic(conn, media_id, auto=tema)
                total += 1
            print(f"[tagging]   lote {i // batch_size + 1}: {len(mapping)} etiquetadas")

    print(f"[tagging] Listo: {total} publicaciones etiquetadas.")
    return total


def main() -> None:
    enable_utf8_console()
    parser = argparse.ArgumentParser(description="Etiqueta publicaciones por tema.")
    parser.add_argument("--all", action="store_true",
                        help="Reclasifica todas (respeta solo los overrides manuales).")
    args = parser.parse_args()
    tag_pending(reclassify_all=args.all)


if __name__ == "__main__":
    main()
