"""Dashboard de análisis de métricas de Instagram (@soy.leo_ai).

    streamlit run dashboard/app.py

Vistas: Resumen (con ratios), Por formato, Por tema, Drivers, Velocidad,
Ranking, Horarios y Hooks. Lee la base que puebla `python -m src.fetch`.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Al correr con `streamlit run`, sys.path[0] es la carpeta del script (dashboard/),
# no la raíz del proyecto. La agregamos para poder importar `src` y `config`.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from config import settings  # noqa: E402
from src import analysis, drivers, guiones, planner  # noqa: E402
from src.db import get_connection, set_topic  # noqa: E402
from src.tagging import TAXONOMY  # noqa: E402

st.set_page_config(page_title="Métricas · @soy.leo_ai", page_icon="📊", layout="wide")

METRICAS_LEGIBLES = {
    "saved": "Guardados",
    "shares": "Compartidos",
    "reach": "Alcance",
    "views": "Reproducciones/Views",
    "interacciones": "Interacciones",
    "likes": "Me gusta",
    "comments": "Comentarios",
}

# Ratios (targets del análisis de drivers). Se muestran como porcentaje.
RATIOS_LEGIBLES = {
    "reach_rate": "Reach rate (alcance/seguidores)",
    "save_rate": "Save rate (guardados/alcance)",
    "share_rate": "Share rate (compartidos/alcance)",
}


@st.cache_data(ttl=300)
def cargar() -> pd.DataFrame:
    return analysis.build_dataset()


@st.cache_data(ttl=300)
def cargar_seguidores() -> pd.DataFrame:
    return analysis.followers_series()


def _formatear(tabla: pd.DataFrame) -> pd.DataFrame:
    """Redondea columnas numéricas para mostrar más limpio."""
    out = tabla.copy()
    for c in out.select_dtypes("number").columns:
        out[c] = out[c].round(2)
    return out


def metrica_selector(df: pd.DataFrame, key: str, default: str = "saved") -> str:
    disponibles = [m for m in METRICAS_LEGIBLES if m in df.columns and df[m].notna().any()]
    if not disponibles:
        return default
    idx = disponibles.index(default) if default in disponibles else 0
    return st.selectbox(
        "Métrica", disponibles, index=idx, key=key,
        format_func=lambda m: METRICAS_LEGIBLES.get(m, m),
    )


# ── Encabezado ────────────────────────────────────────────────────────────────
st.title("📊 Métricas de Instagram — @soy.leo_ai")

if st.button("🔄 Recargar datos"):
    st.cache_data.clear()
    st.rerun()

df = cargar()

if df.empty:
    st.warning(
        "Todavía no hay datos en la base. Corré primero:\n\n"
        "1. `python scripts/refresh_token.py` (token + user_id)\n"
        "2. `python -m src.fetch` (captura las métricas)\n\n"
        f"Base esperada en: `{settings.db_path}`"
    )
    st.stop()

# Navegación con st.radio (no st.tabs): st.tabs NO recuerda la pestaña activa
# tras un rerun, así que al usar un filtro te devolvía a "Resumen". El radio
# persiste su valor vía `key`, y solo se renderiza la vista seleccionada.
VISTAS = ["Resumen", "Generador", "Galería", "Por formato", "Por tema", "Planificador",
          "Drivers", "Velocidad", "Ranking", "Horarios", "Hooks & contenido"]
vista = st.radio("Vista", VISTAS, horizontal=True, label_visibility="collapsed",
                 key="vista_activa")

# ── 1. Resumen ────────────────────────────────────────────────────────────────
if vista == "Resumen":
    st.subheader("Panorama general")
    seg = cargar_seguidores()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Publicaciones", len(df))
    if not seg.empty:
        ultimo = seg.iloc[-1]
        c2.metric("Seguidores", int(ultimo["followers_count"]) if pd.notna(ultimo["followers_count"]) else "—")
    if "reach" in df.columns:
        c3.metric("Alcance promedio", f"{df['reach'].mean():,.0f}" if df["reach"].notna().any() else "—")
    if "engagement_rate" in df.columns and df["engagement_rate"].notna().any():
        c4.metric("Engagement rate medio", f"{df['engagement_rate'].mean() * 100:.1f}%")

    # Ratios que mira el algoritmo (mediana = menos sensible a outliers).
    st.markdown("**Ratios de rendimiento** (mediana — las señales que evalúa Meta)")
    r1, r2, r3, r4 = st.columns(4)
    if "reach_rate" in df.columns and df["reach_rate"].notna().any():
        r1.metric("Reach rate", f"{df['reach_rate'].median() * 100:.0f}%",
                  help="Alcance ÷ seguidores. >100% = salís a no-seguidores.")
    if "save_rate" in df.columns and df["save_rate"].notna().any():
        r2.metric("Save rate", f"{df['save_rate'].median() * 100:.2f}%",
                  help="Guardados ÷ alcance. Señal fuerte de valor.")
    if "share_rate" in df.columns and df["share_rate"].notna().any():
        r3.metric("Share rate", f"{df['share_rate'].median() * 100:.2f}%",
                  help="Compartidos ÷ alcance. Señal fuerte de distribución.")
    if "breakout" in df.columns:
        n_break = int(df["breakout"].sum())
        r4.metric("Breakout", f"{n_break} / {len(df)}",
                  help="Posts cuyo alcance superó tu nº de seguidores.")

    if not seg.empty and seg["followers_count"].notna().any():
        st.markdown("**Evolución de seguidores**")
        st.line_chart(seg.set_index("captured_at")["followers_count"])
    else:
        st.info("La evolución de seguidores se va a llenar a medida que corras `fetch` "
                "en distintos días (cada corrida guarda un snapshot).")

    st.markdown("**Cadencia de publicación (por mes)**")
    if df["publicado"].notna().any():
        publicados = df.dropna(subset=["publicado"])
        por_mes = publicados.groupby(publicados["publicado"].dt.strftime("%Y-%m")).size()
        st.bar_chart(por_mes)

# ── 2. Generador ──────────────────────────────────────────────────────────────
elif vista == "Generador":
    st.subheader("✍️ Generador de guiones con estrategia")
    st.caption(f"Genera guiones completos con **{guiones.engine_name()}**, primados con tus datos "
               "reales + las 5 reglas de intención (señal objetivo, demostración, "
               "consistencia temática, CTA que crece la cuenta).")

    OBJ_LABEL = {"alcance": "Alcance (que te descubran)",
                 "guardados": "Guardados (valor / autoridad)",
                 "compartidos": "Compartir (viral)"}
    c1, c2 = st.columns(2)
    objetivo = c1.selectbox("Objetivo", list(guiones.FUNNEL), key="gen_obj",
                            format_func=lambda o: OBJ_LABEL[o])
    fn = guiones.FUNNEL[objetivo]
    formato = c2.selectbox("Formato", ["(auto)", "Reel", "Carrusel"], key="gen_fmt")
    temas_disp = ["(auto)"] + sorted(
        t for t in df["tema"].dropna().unique() if t not in ("sin_etiquetar", "otro"))
    tema = c1.selectbox("Tema", temas_disp, key="gen_tema")
    cantidad = c2.slider("Cantidad", 1, 3, 2, key="gen_cant")
    notas = st.text_input("Tema puntual / notas (opcional)", key="gen_notas",
                          placeholder="Ej: mostrar un cómputo de steel frame en 2 minutos")
    st.caption(f"↳ Rol de embudo: {fn['rol']} · señal a maximizar: **{fn['senal']}**")

    if st.button("✍️ Generar guiones", key="gen_btn", type="primary"):
        prompt = guiones.build_prompt(
            objetivo, None if tema == "(auto)" else tema,
            None if formato == "(auto)" else formato, cantidad, notas.strip(), df)
        with st.spinner(f"Generando con {guiones.engine_name()}… (puede tardar 10-40s)"):
            try:
                st.session_state["gen_out"] = guiones.generate(prompt)
            except Exception as exc:  # noqa: BLE001
                st.session_state["gen_out"] = None
                st.error(f"No se pudo generar: {exc}")

    if st.session_state.get("gen_out"):
        st.divider()
        st.markdown(st.session_state["gen_out"])
        st.download_button("⬇️ Descargar (.md)", st.session_state["gen_out"],
                           file_name="guiones.md", mime="text/markdown")

# ── 3. Galería ────────────────────────────────────────────────────────────────
elif vista == "Galería":
    st.subheader("Galería de publicaciones")
    st.caption("Miniatura + métricas de cada post, ordenados por rendimiento. "
               "Tocá el link para abrirlo en Instagram.")
    tiene_thumbs = "thumb_local" in df.columns and df["thumb_local"].notna().any()
    if not tiene_thumbs:
        st.info("Las miniaturas se cachean en la próxima corrida de `fetch`. "
                "Volvé a entrar después de la siguiente captura.")

    # La galería no incluye fotos (no aportan; foco en reels/carruseles/historias).
    gal = df[df["formato"] != "Foto"]
    colf, colm = st.columns([1, 1])
    formatos = ["Todos"] + sorted(gal["formato"].dropna().unique().tolist())
    fsel = colf.selectbox("Formato", formatos, key="gal_fmt")
    with colm:
        met = metrica_selector(df, key="gal_metric", default="reach")

    vis = gal if fsel == "Todos" else gal[gal["formato"] == fsel]
    if met in vis.columns:
        vis = vis.dropna(subset=[met]).sort_values(met, ascending=False)
    vis = vis.head(30)

    n_cols = 3
    cols = st.columns(n_cols)
    for i, (_, r) in enumerate(vis.iterrows()):
        with cols[i % n_cols]:
            if r.get("thumb_local"):
                st.image(r["thumb_local"], use_container_width=True)
            valor = r.get(met)
            titulo = f"**{r['formato']}** · {r.get('tema', '')}"
            st.markdown(titulo)
            if pd.notna(valor):
                st.markdown(f"{METRICAS_LEGIBLES.get(met, met)}: **{valor:,.0f}**")
            st.caption((r.get("hook") or "")[:70])
            if r.get("permalink"):
                st.markdown(f"[Ver en Instagram ↗]({r['permalink']})")
            st.divider()

# ── 3. Por formato ────────────────────────────────────────────────────────────
elif vista == "Por formato":
    st.subheader("¿Qué formato rinde mejor?")
    tabla = analysis.by_format(df)
    if tabla.empty:
        st.info("Sin datos suficientes.")
    else:
        st.dataframe(_formatear(tabla), use_container_width=True)
        met = metrica_selector(df, key="fmt_metric")
        prom = df.groupby("formato")[met].mean().sort_values(ascending=False)
        st.markdown(f"**{METRICAS_LEGIBLES.get(met, met)} promedio por formato**")
        st.bar_chart(prom)

# ── 3. Por tema ───────────────────────────────────────────────────────────────
elif vista == "Por tema":
    st.subheader("¿Qué temas traccionan? (foco en guardados y compartidos)")
    tabla = analysis.by_topic(df)
    if tabla.empty:
        st.info("Sin datos suficientes.")
    else:
        st.dataframe(_formatear(tabla), use_container_width=True)
        met = metrica_selector(df, key="tema_metric")
        prom = df.groupby("tema")[met].mean().sort_values(ascending=False)
        st.markdown(f"**{METRICAS_LEGIBLES.get(met, met)} promedio por tema**")
        st.bar_chart(prom)

    st.divider()
    st.markdown("### ✏️ Corregir temas a mano")
    st.caption("El tema manual tiene prioridad sobre el automático. Editá la columna "
               "«tema manual» y guardá.")
    editable = df[["media_id", "publicado", "formato", "hook", "tema"]].copy()
    editable["tema manual"] = df["topic_manual"]
    editado = st.data_editor(
        editable,
        column_config={
            "tema manual": st.column_config.SelectboxColumn(
                "tema manual", options=[None] + TAXONOMY
            ),
            "media_id": st.column_config.TextColumn("media_id", disabled=True),
        },
        hide_index=True,
        use_container_width=True,
        key="editor_temas",
    )
    if st.button("💾 Guardar temas"):
        cambios = 0
        with get_connection() as conn:
            for _, fila in editado.iterrows():
                nuevo = fila["tema manual"]
                if pd.notna(nuevo) and nuevo:
                    set_topic(conn, fila["media_id"], manual=str(nuevo))
                    cambios += 1
        st.success(f"{cambios} temas actualizados.")
        st.cache_data.clear()

# ── 4. Planificador ───────────────────────────────────────────────────────────
elif vista == "Planificador":
    st.subheader("¿Qué publicar, qué día y a qué hora?")
    st.caption("Cruce de formato · tema · día · franja horaria (hora local, "
               f"UTC{settings.local_utc_offset:+d}) contra el rendimiento. "
               "⚠️ Se muestra `n` (nº de posts) en cada combo: cuanto mayor, más "
               "confiable. Se afina con la medición continua.")
    met = metrica_selector(df, key="plan_metric", default="reach")

    st.info(planner.recommendation_text(df, met))

    st.markdown("**Mejores combos** (formato · día · franja, mínimo 3 posts)")
    slots = planner.best_slots(df, met, min_n=3, top=12)
    if slots.empty:
        st.caption("Todavía no hay combos con suficientes posts para esta métrica.")
    else:
        st.dataframe(
            slots.rename(columns={"dia_semana": "día",
                                  "promedio": METRICAS_LEGIBLES.get(met, met)}),
            use_container_width=True, hide_index=True,
        )

    def _heat(dim: str, titulo: str):
        medias, conteos = planner.matrix(df, dim, met)
        if medias.empty:
            st.caption(f"Sin datos para {titulo}.")
            return
        m_long = medias.reset_index().melt(id_vars=dim, var_name="día", value_name="valor")
        c_long = conteos.reset_index().melt(id_vars=dim, var_name="día", value_name="n")
        largo = m_long.merge(c_long, on=[dim, "día"]).dropna(subset=["valor"])
        orden = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
        base = alt.Chart(largo).encode(
            x=alt.X("día:O", sort=orden, title=None),
            y=alt.Y(f"{dim}:O", title=None),
        )
        heat = base.mark_rect().encode(
            color=alt.Color("valor:Q", scale=alt.Scale(scheme="greens"),
                            title=METRICAS_LEGIBLES.get(met, met)),
            tooltip=[alt.Tooltip(f"{dim}:O"), alt.Tooltip("día:O"),
                     alt.Tooltip("valor:Q", format=",.0f",
                                 title=METRICAS_LEGIBLES.get(met, met)),
                     alt.Tooltip("n:Q", title="nº posts")],
        )
        texto = base.mark_text(baseline="middle", fontSize=11).encode(
            text=alt.Text("n:Q", format="d"), color=alt.value("#333"),
        )
        st.markdown(f"**{titulo}** (color = {METRICAS_LEGIBLES.get(met, met)}, "
                    "número = nº de posts)")
        st.altair_chart((heat + texto).properties(height=alt.Step(40)),
                        use_container_width=True)

    _heat("formato", "Formato × Día")
    _heat("tema", "Tema × Día")

# ── 5. Drivers ────────────────────────────────────────────────────────────────
elif vista == "Drivers":
    st.subheader("¿Qué atributos del creativo mueven el rendimiento?")
    st.caption("Correlación (Spearman) de features del creativo vs los ratios. "
               "⚠️ Señales direccionales: con pocos posts y guardados bajos, son "
               "hipótesis para iterar, no leyes. Se afinan con cada medición.")

    cor = drivers.correlations(df)
    if cor.empty:
        st.info("Sin datos suficientes.")
    else:
        cor_legible = cor.rename(index={
            "cap_len": "largo caption", "word_count": "nº palabras",
            "n_emojis": "nº emojis", "has_question": "tiene pregunta",
            "has_number": "tiene número", "n_hashtags": "nº hashtags",
            "hook_len": "largo hook", "hora": "hora del día",
        }, columns=RATIOS_LEGIBLES)
        orden_feat = ["largo caption", "nº palabras", "largo hook", "nº emojis",
                      "nº hashtags", "tiene número", "tiene pregunta", "hora del día"]
        # Heatmap de correlaciones (verde = +, rojo = −). Altura por fila fija
        # (alt.Step) para que se vean TODAS las etiquetas, no una de cada dos.
        largo = cor_legible.reset_index(names="feature").melt(
            id_vars="feature", var_name="ratio", value_name="corr")
        base = alt.Chart(largo).encode(
            x=alt.X("ratio:N", title=None, axis=alt.Axis(labelLimit=220)),
            y=alt.Y("feature:N", title=None, sort=orden_feat,
                    axis=alt.Axis(labelLimit=220)),
        )
        heat = base.mark_rect().encode(
            color=alt.Color("corr:Q",
                            scale=alt.Scale(scheme="redyellowgreen", domain=[-0.3, 0.3]),
                            title="correlación"),
            tooltip=[alt.Tooltip("feature:N", title="atributo"),
                     alt.Tooltip("ratio:N", title="ratio"),
                     alt.Tooltip("corr:Q", format="+.2f", title="correlación")],
        )
        texto = base.mark_text(baseline="middle", fontSize=12).encode(
            text=alt.Text("corr:Q", format="+.2f"), color=alt.value("black"),
        )
        st.altair_chart((heat + texto).properties(height=alt.Step(38)),
                        use_container_width=True)

        st.markdown("**Tus mejores vs peores creativos** (cuartil sup. vs inf. por reach rate)")
        qc = drivers.quartile_compare(df, "reach_rate")
        if not qc.empty:
            st.dataframe(qc, use_container_width=True, hide_index=True)
        mix = drivers.top_quartile_mix(df, "reach_rate")
        if mix:
            colf, colt = st.columns(2)
            colf.markdown("**Formato del top cuartil**")
            colf.bar_chart(pd.Series(mix["formato"]))
            colt.markdown("**Tema del top cuartil**")
            colt.bar_chart(pd.Series(mix["tema"]))

# ── 5. Velocidad ──────────────────────────────────────────────────────────────
elif vista == "Velocidad":
    st.subheader("Velocidad: cómo acumula cada post en el tiempo")
    n_snap = analysis.snapshot_count()
    st.caption("La velocidad de acumulación en las primeras 24-48 h predice si Meta "
               "va a empujar el post. Se construye midiendo el mismo post varios días.")
    if n_snap < 2:
        st.info(f"Por ahora hay **{n_snap} snapshot**. Corré `python -m src.fetch` en "
                "días distintos (idealmente diario tras publicar) para ver la curva. "
                "El carrusel que publiques va a mostrar su acumulación acá.")
    # Selector de post (recientes primero) — funciona con 1 o más snapshots.
    recientes = df.dropna(subset=["publicado"]).sort_values("publicado", ascending=False)
    opciones = recientes.head(30)
    if not opciones.empty:
        etiqueta = {r["media_id"]: f"{r['publicado'].date()} · {r['formato']} · {(r['hook'] or '')[:40]}"
                    for _, r in opciones.iterrows()}
        sel = st.selectbox("Publicación", list(etiqueta), format_func=lambda m: etiqueta[m],
                           key="vel_post")
        hist = analysis.metric_history(sel)
        if not hist.empty:
            foco = ["reach", "saved", "shares", "views"]
            h = hist[hist["metric_name"].isin(foco)]
            if h["horas_desde_publicado"].notna().any() and n_snap >= 2:
                line = (
                    alt.Chart(h).mark_line(point=True).encode(
                        x=alt.X("horas_desde_publicado:Q", title="Horas desde publicado"),
                        y=alt.Y("value:Q", title="Valor acumulado"),
                        color=alt.Color("metric_name:N", title="Métrica"),
                        tooltip=["metric_name", "value", "horas_desde_publicado"],
                    ).properties(height=300)
                )
                st.altair_chart(line, use_container_width=True)
            else:
                st.markdown("**Valores actuales** (un solo punto por ahora):")
                st.dataframe(
                    h[["metric_name", "value", "horas_desde_publicado"]],
                    use_container_width=True, hide_index=True,
                )

# ── 6. Ranking ────────────────────────────────────────────────────────────────
elif vista == "Ranking":
    st.subheader("Mejores y peores publicaciones")
    met = metrica_selector(df, key="rank_metric")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**🏆 Top 10 por {METRICAS_LEGIBLES.get(met, met)}**")
        st.dataframe(analysis.ranking(df, met, 10, ascending=False),
                     use_container_width=True, hide_index=True)
    with col2:
        st.markdown(f"**🔻 Bottom 10 por {METRICAS_LEGIBLES.get(met, met)}**")
        st.dataframe(analysis.ranking(df, met, 10, ascending=True),
                     use_container_width=True, hide_index=True)

# ── 7. Horarios ───────────────────────────────────────────────────────────────
elif vista == "Horarios":
    st.subheader("¿Cuándo conviene publicar?")
    met = metrica_selector(df, key="time_metric", default="reach")
    tabla = analysis.timing(df, met)
    if tabla.empty:
        st.info("Sin datos suficientes para el heatmap.")
    else:
        st.caption(f"Promedio por día × hora **local** (UTC{settings.local_utc_offset:+d}).")
        orden_dias = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
        largo = (
            tabla.reset_index()
            .melt(id_vars="dia_semana", var_name="hora", value_name="valor")
            .dropna(subset=["valor"])
        )
        heat = (
            alt.Chart(largo)
            .mark_rect()
            .encode(
                x=alt.X("hora:O", title="Hora del día"),
                y=alt.Y("dia_semana:O", sort=orden_dias, title="Día"),
                color=alt.Color("valor:Q", scale=alt.Scale(scheme="greens"),
                                title=METRICAS_LEGIBLES.get(met, met)),
                tooltip=[
                    alt.Tooltip("dia_semana:O", title="Día"),
                    alt.Tooltip("hora:O", title="Hora"),
                    alt.Tooltip("valor:Q", title=METRICAS_LEGIBLES.get(met, met), format=",.0f"),
                ],
            )
            .properties(height=260)
        )
        st.altair_chart(heat, use_container_width=True)

# ── 8. Hooks & contenido ──────────────────────────────────────────────────────
elif vista == "Hooks & contenido":
    st.subheader("Hooks que funcionaron")
    st.caption("Primeras líneas de tus publicaciones con mejor rendimiento. "
               "Esto alimenta tu prompt de creación de contenido "
               "(`python scripts/export_content_brief.py`).")
    met = metrica_selector(df, key="hook_metric")
    hooks = analysis.mine_hooks(df, met, 20)
    if hooks.empty:
        st.info("Sin datos suficientes.")
    else:
        st.dataframe(hooks, use_container_width=True, hide_index=True)
