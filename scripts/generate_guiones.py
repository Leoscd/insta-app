"""Generador de guiones con estrategia de crecimiento (CLI).

La lógica vive en `src/guiones.py` (compartida con el dashboard). Este script es
el envoltorio de línea de comandos.

    python scripts/generate_guiones.py --objetivo guardados --cantidad 3
    python scripts/generate_guiones.py --objetivo alcance --tema herramienta_demo --formato Reel
    python scripts/generate_guiones.py --dry           # imprime el prompt sin llamar a la IA

Salida: imprime los guiones y los agrega a data/guiones/guiones_<fecha>.md
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import enable_utf8_console, settings  # noqa: E402
from src import analysis, guiones  # noqa: E402


def main() -> None:
    enable_utf8_console()
    ap = argparse.ArgumentParser(description="Genera guiones con estrategia de crecimiento.")
    ap.add_argument("--objetivo", choices=list(guiones.FUNNEL), default="guardados")
    ap.add_argument("--tema", default=None, help="Tema puntual (default: lo elige por objetivo).")
    ap.add_argument("--formato", choices=["Reel", "Carrusel"], default=None)
    ap.add_argument("--cantidad", type=int, default=3)
    ap.add_argument("--notas", default="", help="Tema/ángulo puntual del guion.")
    ap.add_argument("--dry", action="store_true", help="Imprime el prompt sin llamar a la IA.")
    args = ap.parse_args()

    df = analysis.build_dataset()
    if df.empty:
        raise SystemExit("No hay datos. Corré primero: python -m src.fetch")

    prompt = guiones.build_prompt(args.objetivo, args.tema, args.formato,
                                  max(1, min(5, args.cantidad)), args.notas.strip(), df)
    if args.dry:
        print(prompt)
        return

    print(f"[guiones] Generando con {guiones.engine_name()} · objetivo {args.objetivo}…")
    try:
        texto = guiones.generate(prompt)
    except RuntimeError as exc:
        raise SystemExit(str(exc))

    out = settings.db_path.parent / "guiones" / f"guiones_{date.today():%Y-%m-%d}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(f"\n\n# {args.objetivo} · {args.formato or guiones.FUNNEL[args.objetivo]['formato']} "
                f"· {date.today():%Y-%m-%d %H:%M}\n\n{texto}\n")
    print(texto)
    print(f"\n[guiones] Guardado en: {out}")


if __name__ == "__main__":
    main()
