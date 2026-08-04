"""Genera el "brief de contenido" que alimenta tu prompt de creación.

Toma tus métricas reales y produce un bloque markdown con la EVIDENCIA de qué
está funcionando (formatos, temas, hooks, horarios). Ese bloque se pega en tu
prompt de matriz de ads como una sección nueva:

    ## DATOS DE RENDIMIENTO (no inventar — usar esto)

Así el modelo deja de adivinar hooks/formatos y trabaja sobre lo que YA le
funciona a tu audiencia.

    python scripts/export_content_brief.py
    python scripts/export_content_brief.py --metric shares --out mi_brief.md
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from config import enable_utf8_console, settings  # noqa: E402
from src import analysis  # noqa: E402


def _linea_formatos(df: pd.DataFrame) -> str:
    t = analysis.by_format(df)
    if t.empty:
        return "- (sin datos)"
    filas = []
    for _, r in t.iterrows():
        saved = r.get("saved")
        reach = r.get("reach")
        filas.append(
            f"- **{r['formato']}** ({int(r['publicaciones'])} publicaciones): "
            f"guardados ~{saved:.0f} · alcance ~{reach:.0f}"
            if pd.notna(saved) and pd.notna(reach)
            else f"- **{r['formato']}** ({int(r['publicaciones'])} publicaciones)"
        )
    return "\n".join(filas)


def _linea_temas(df: pd.DataFrame) -> str:
    t = analysis.by_topic(df)
    if t.empty:
        return "- (sin datos)"
    t = t[t["tema"] != "sin_etiquetar"]
    filas = []
    for _, r in t.head(6).iterrows():
        saved = r.get("saved")
        shares = r.get("shares")
        detalle = []
        if pd.notna(saved):
            detalle.append(f"guardados ~{saved:.0f}")
        if pd.notna(shares):
            detalle.append(f"compartidos ~{shares:.0f}")
        filas.append(f"- **{r['tema']}** ({int(r['publicaciones'])}): " + " · ".join(detalle))
    return "\n".join(filas) if filas else "- (sin publicaciones etiquetadas todavía)"


def _linea_hooks(df: pd.DataFrame, metric: str) -> str:
    h = analysis.mine_hooks(df, metric, 10)
    if h.empty:
        return "- (sin datos)"
    return "\n".join(
        f'- "{r["hook"][:140]}"  _(tema: {r["tema"]}, {r["formato"]})_'
        for _, r in h.iterrows()
    )


def _linea_horarios(df: pd.DataFrame) -> str:
    t = analysis.timing(df, "reach")
    if t.empty:
        return "- (sin datos)"
    # Mejor combinación día×hora por alcance promedio.
    apilado = t.stack()
    if apilado.empty:
        return "- (sin datos)"
    mejores = apilado.sort_values(ascending=False).head(3)
    return "\n".join(f"- {dia} a las {int(hora)}:00 hs (alcance ~{val:.0f})"
                     for (dia, hora), val in mejores.items())


def construir_brief(metric: str) -> str:
    df = analysis.build_dataset()
    if df.empty:
        return ("No hay datos todavía. Corré `python -m src.fetch` primero.")

    etiquetadas = (df["tema"] != "sin_etiquetar").sum()

    return f"""## DATOS DE RENDIMIENTO (no inventar — usar esto)

_Generado el {date.today().isoformat()} a partir de {len(df)} publicaciones
({etiquetadas} etiquetadas por tema). Métrica de referencia: {metric}._

### Formatos que mejor rinden (priorizá los de arriba)
{_linea_formatos(df)}

### Temas que más traccionan (por guardados y compartidos)
{_linea_temas(df)}

### Hooks probados (primeras líneas de tus publicaciones top)
Usá estos como base para el EJE 1 (Hooks). Ya conectaron con tu audiencia:
{_linea_hooks(df, metric)}

### Mejores horarios para publicar
{_linea_horarios(df)}

### Naming convention sugerido para Ads Manager
Para poder trackear qué variable gana, nombrá cada ad así:
`[formato]_[tema]_[tipohook]_[fecha]`
Ejemplo: `reel_caso_de_exito_dolor_2026-08`
- **formato**: reel / carrusel / foto
- **tema**: uno de tus temas de arriba
- **tipohook**: dolor / pregunta / dato / negacion / historia / resultado
- **fecha**: año-mes

> Cómo usar este bloque: pegalo dentro de tu prompt de matriz de contenido,
> justo después del CONTEXTO DEL NEGOCIO. Indicá en el prompt:
> "Priorizá los formatos y temas de la sección DATOS DE RENDIMIENTO y basá los
> hooks del EJE 1 en los hooks probados."
"""


def main() -> None:
    enable_utf8_console()
    parser = argparse.ArgumentParser(description="Genera el brief de contenido.")
    parser.add_argument("--metric", default="saved",
                        help="Métrica de referencia (saved, shares, reach…). Default: saved.")
    parser.add_argument("--out", default=None,
                        help="Ruta de salida. Default: data/exports/brief_<fecha>.md")
    args = parser.parse_args()

    brief = construir_brief(args.metric)

    out = Path(args.out) if args.out else (
        settings.db_path.parent / "exports" / f"brief_{date.today().isoformat()}.md"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(brief, encoding="utf-8")

    print(brief)
    print(f"\n[brief] Guardado en: {out}")


if __name__ == "__main__":
    main()
