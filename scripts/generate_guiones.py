"""Generador de guiones con estrategia de crecimiento.

Lee los datos reales (formatos/temas/hooks/mejores momentos) y genera N guiones
de Instagram (reel/carrusel) para @soy.leo_ai — con CARGA DE INTENCIÓN: cada
guion se diseña para ganar la señal que hace crecer la cuenta y "entrenar" al
algoritmo con contenido de alto valor, no solo para verse lindo.

Motor: API de Claude (usa ANTHROPIC_API_KEY del .env). El mismo motor mejora el
auto-etiquetado.

    python scripts/generate_guiones.py --objetivo guardados --cantidad 3
    python scripts/generate_guiones.py --objetivo alcance --tema herramienta_demo --formato Reel
    python scripts/generate_guiones.py --dry           # imprime el prompt sin llamar a la IA

Salida: imprime los guiones y los guarda en data/guiones/guiones_<fecha>.md
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import enable_utf8_console, settings  # noqa: E402
from src import analysis, planner  # noqa: E402

# ── Estrategia por objetivo: rol de embudo · señal objetivo · CTA · formato ────
# Esto es el "corazón" del generador: NO solo formatea, elige la estrategia.
FUNNEL = {
    "alcance": {
        "rol": "DESCUBRIMIENTO (que te encuentren no-seguidores, tope del embudo)",
        "senal": "alcance + compartidos",
        "formato": "Reel",
        "temas": ["dolor_tiempo", "herramienta_demo", "caso_exito"],
        "cta": "invitá a comentar una palabra clave o a compartir el reel con un colega",
        "por_que": "los reels te dan ~1.8x más alcance; el dolor identificable se comparte",
    },
    "guardados": {
        "rol": "VALOR / AUTORIDAD (que te guarden = 'esto me sirve', construye autoridad)",
        "senal": "guardados",
        "formato": "Carrusel",
        "temas": ["herramienta_demo", "caso_exito", "mito_ia"],
        "cta": "pediles que GUARDEN el carrusel para aplicarlo, y que comenten su caso",
        "por_que": "los carruseles accionables se guardan; la gente vuelve a ellos",
    },
    "compartidos": {
        "rol": "VIRALIZACIÓN (que lo reenvíen, distribución orgánica)",
        "senal": "compartidos",
        "formato": "Reel",
        "temas": ["dolor_tiempo", "caso_exito", "evento"],
        "cta": "cerrá con 'mandáselo a un arquitecto que lo necesite'",
        "por_que": "el dolor concreto y los casos de éxito son lo más reenviado",
    },
}


def _fmt_num(x) -> str:
    return f"{x:.2f}" if isinstance(x, (int, float)) else str(x)


def build_datos(df) -> str:
    """Sección DATOS DE RENDIMIENTO REALES para anclar la generación."""
    bf = analysis.by_format(df)
    por_formato = " | ".join(
        f"{r['formato']}: alcance {r['reach']:.0f}, guardados {r['saved']:.2f}, "
        f"compartidos {r['shares']:.2f}"
        for _, r in bf.iterrows() if r["formato"] != "Foto"
    )
    bt = analysis.by_topic(df)
    bt = bt[bt["tema"] != "sin_etiquetar"].sort_values("saved", ascending=False)
    por_tema = ", ".join(
        f"{r['tema']} (g {r['saved']:.2f}·c {r['shares']:.2f})"
        for _, r in bt.head(6).iterrows()
    )
    hooks = analysis.mine_hooks(df, "saved", 8)
    hook_list = "\n".join(f'   · "{r["hook"]}"' for _, r in hooks.iterrows())
    foll = analysis.latest_followers()
    return (
        f"Base: {len(df)} publicaciones, {foll} seguidores.\n"
        f"- Por formato → {por_formato}\n"
        f"- Temas que más traccionan → {por_tema}\n"
        f"- Hooks míos que YA funcionaron (referencia de estilo, no copiar literal):\n{hook_list}"
    )


def build_prompt(objetivo: str, tema: str | None, formato: str | None,
                 cantidad: int, notas: str, df) -> str:
    fn = FUNNEL[objetivo]
    formato = formato or fn["formato"]
    metric = "reach" if objetivo == "alcance" else "saved"
    cand = planner.best_slots(df, metric, min_n=3, top=5)
    recs = cand.to_dict("records") if not cand.empty else []
    slot = next((s for s in recs if s.get("formato") == formato), None)
    if slot is None and recs:
        slot = recs[0]
    momento = (f"{slot['formato']} el {slot['dia_semana']} en la franja {slot['franja']}"
               if slot else "según tu planificador")
    tema_txt = tema or f"elegí el mejor entre {', '.join(fn['temas'])} según el ángulo"

    return f"""Sos guionista de contenido de respuesta directa para Instagram, experto en captar la atención en los primeros 3 segundos Y en diseñar contenido que el ALGORITMO premia con distribución.

# QUIÉN
Leonardo Díaz (@soy.leo_ai): arquitecto + científico de datos. Consultor de IA aplicada a la arquitectura. Ayuda a arquitectos/estudios a agilizar tareas operativas (presupuestos, cómputos, normativas, propuestas, renders) con IA, para recuperar tiempo y cobrar por valor. Tono: directo, sin corporativo, autoridad técnica + empatía, español rioplatense (vos). Nada de "revoluciona tu vida".

# DATOS DE RENDIMIENTO REALES (usar como evidencia, NO inventar)
{build_datos(df)}

# ESTRATEGIA DE ESTE PEDIDO (obligatoria — es lo que hace crecer la cuenta)
Objetivo: {objetivo.upper()} → rol en el embudo: {fn['rol']}.
Señal del algoritmo a maximizar: {fn['senal']}. ({fn['por_que']})
Las 5 reglas que TODO guion debe cumplir:
1. Optimizar por la SEÑAL, no por likes: cada guion debe empujar {fn['senal']}.
2. CONSISTENCIA TEMÁTICA: quedate estricto dentro del nicho (IA para arquitectos) para que el algoritmo clasifique la cuenta y la muestre a más arquitectos. No te vayas del tema.
3. MOSTRAR > CONTAR: incluí un momento concreto de DEMOSTRACIÓN (pantalla del sistema funcionando, antes/después, un número real). Es lo que construye autoridad y se guarda.
4. RETENCIÓN: hook que frene el scroll en 3 seg y una razón para quedarse mirando/deslizando (la velocidad de las primeras horas define la distribución).
5. CTA que dispara la señal: {fn['cta']}. Nunca "seguime" a secas.

# PEDIDO
Generá {cantidad} guion(es) de {formato} sobre el tema: {tema_txt}.
{("Tema puntual / notas: " + notas) if notas else ""}
Para CADA guion entregá, en este orden:
1. HOOK — 2 variantes (primeros 3 seg / primera slide), en el estilo de mis hooks probados.
2. DESARROLLO — {"reel: guion HABLADO (a cámara) + TEXTO EN PANTALLA por bloque, con el momento de demostración marcado" if formato == "Reel" else "carrusel: 6-8 slides, slide por slide, texto corto y contundente, con la demostración en el medio"}.
3. POR QUÉ FUNCIONA — 1 línea: qué señal ({fn['senal']}) busca y por qué.
4. CTA — específico, dispara {fn['senal']}.
5. PUBLICAR — {momento}. Naming: {formato.lower()}_{{tema}}_{objetivo}_{date.today():%Y-%m}.

Reglas de forma: texto limpio, sin corchetes ni placeholders, listo para grabar/diseñar. Español rioplatense."""


def generate(prompt: str) -> str:
    settings.require("anthropic_api_key")
    import anthropic
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")


def main() -> None:
    enable_utf8_console()
    ap = argparse.ArgumentParser(description="Genera guiones con estrategia de crecimiento.")
    ap.add_argument("--objetivo", choices=list(FUNNEL), default="guardados")
    ap.add_argument("--tema", default=None, help="Tema puntual (default: lo elige por objetivo).")
    ap.add_argument("--formato", choices=["Reel", "Carrusel"], default=None)
    ap.add_argument("--cantidad", type=int, default=3)
    ap.add_argument("--notas", default="", help="Tema/ángulo puntual del guion.")
    ap.add_argument("--dry", action="store_true", help="Imprime el prompt sin llamar a la IA.")
    args = ap.parse_args()

    df = analysis.build_dataset()
    if df.empty:
        raise SystemExit("No hay datos. Corré primero: python -m src.fetch")

    prompt = build_prompt(args.objetivo, args.tema, args.formato,
                          max(1, min(5, args.cantidad)), args.notas.strip(), df)

    if args.dry:
        print(prompt)
        return

    print(f"[guiones] Generando {args.cantidad} guion(es) · objetivo {args.objetivo}…")
    texto = generate(prompt)

    out = settings.db_path.parent / "guiones" / f"guiones_{date.today():%Y-%m-%d}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(f"\n\n# {args.objetivo} · {args.formato or FUNNEL[args.objetivo]['formato']} "
                f"· {date.today():%Y-%m-%d %H:%M}\n\n{texto}\n")
    print(texto)
    print(f"\n[guiones] Guardado en: {out}")


if __name__ == "__main__":
    main()
