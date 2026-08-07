"""Lógica del generador de guiones con estrategia de crecimiento.

Compartida por el CLI (`scripts/generate_guiones.py`) y por la pestaña
"Generador" del dashboard. Cada guion se diseña para ganar la señal que hace
crecer la cuenta (las 5 reglas de intención), no solo para verse lindo.

Motor pluggable: MiniMax si hay MINIMAX_API_KEY, si no Claude.
"""
from __future__ import annotations

from datetime import date

from config import settings
from src import analysis, planner

# ── Estrategia por objetivo: rol de embudo · señal · CTA · formato ────────────
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
    slot = next((s for s in planner.best_slots(df, metric, min_n=3, top=5)
                 if s.get("formato") == formato), None)
    if slot is None:
        slots = planner.best_slots(df, "saved", min_n=3, top=1)
        slot = slots.iloc[0].to_dict() if not slots.empty else None
    momento = (f"{slot['formato']} el {slot['dia_semana']} en la franja {slot['franja']}"
               if slot else "según tu planificador")
    tema_txt = tema or f"elegí el mejor entre {', '.join(fn['temas'])} según el ángulo"
    desarrollo = ("reel: guion HABLADO (a cámara) + TEXTO EN PANTALLA por bloque, con el "
                  "momento de demostración marcado" if formato == "Reel" else
                  "carrusel: 6-8 slides, slide por slide, texto corto y contundente, con la "
                  "demostración en el medio")

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
2. DESARROLLO — {desarrollo}.
3. POR QUÉ FUNCIONA — 1 línea: qué señal ({fn['senal']}) busca y por qué.
4. CTA — específico, dispara {fn['senal']}.
5. PUBLICAR — {momento}. Naming: {formato.lower()}_{{tema}}_{objetivo}_{date.today():%Y-%m}.

Reglas de forma: texto limpio, sin corchetes ni placeholders, listo para grabar/diseñar. Español rioplatense."""


def _generate_minimax(prompt: str) -> str:
    """Genera con la API de MiniMax (endpoint OpenAI-compatible)."""
    import requests
    resp = requests.post(
        f"{settings.minimax_base_url}/chat/completions",
        headers={"Authorization": f"Bearer {settings.minimax_api_key}",
                 "Content-Type": "application/json"},
        json={"model": settings.minimax_model,
              "messages": [{"role": "user", "content": prompt}],
              "max_tokens": 4000},
        timeout=180,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"[minimax] error {resp.status_code}: {resp.text[:400]}")
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise RuntimeError(f"[minimax] respuesta inesperada: {str(data)[:400]}")


def _generate_claude(prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(
        model=settings.anthropic_model, max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")


def engine_name() -> str:
    """Qué motor se va a usar con la config actual."""
    if settings.minimax_api_key:
        return "MiniMax"
    if settings.anthropic_api_key:
        return "Claude"
    return "ninguno"


def generate(prompt: str) -> str:
    """Genera con el motor disponible: MiniMax si hay key, si no Claude."""
    if settings.minimax_api_key:
        return _generate_minimax(prompt)
    if settings.anthropic_api_key:
        return _generate_claude(prompt)
    raise RuntimeError("Falta MINIMAX_API_KEY o ANTHROPIC_API_KEY en el .env")
