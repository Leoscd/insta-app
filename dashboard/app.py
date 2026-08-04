"""Dashboard de análisis de métricas de Instagram (@soy.leo_ai).

    streamlit run dashboard/app.py

Seis vistas: Resumen, Por formato, Por tema, Ranking, Horarios y Hooks.
Lee la base que puebla `python -m src.fetch`.
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
from src import analysis  # noqa: E402
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

tabs = st.tabs(
    ["Resumen", "Por formato", "Por tema", "Ranking", "Horarios", "Hooks & contenido"]
)

# ── 1. Resumen ────────────────────────────────────────────────────────────────
with tabs[0]:
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

# ── 2. Por formato ────────────────────────────────────────────────────────────
with tabs[1]:
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
with tabs[2]:
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

# ── 4. Ranking ────────────────────────────────────────────────────────────────
with tabs[3]:
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

# ── 5. Horarios ───────────────────────────────────────────────────────────────
with tabs[4]:
    st.subheader("¿Cuándo conviene publicar?")
    met = metrica_selector(df, key="time_metric", default="reach")
    tabla = analysis.timing(df, met)
    if tabla.empty:
        st.info("Sin datos suficientes para el heatmap.")
    else:
        st.caption("Promedio por día de semana × hora (según la marca temporal de la API).")
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

# ── 6. Hooks & contenido ──────────────────────────────────────────────────────
with tabs[5]:
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
