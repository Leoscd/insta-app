"""Planificador: qué formato/tema publicar, qué día y en qué franja horaria.

Cruza formato · tema · día · franja horaria (hora local) contra el rendimiento
para responder "¿qué me conviene publicar mañana y a qué hora?".

⚠️ Honestidad estadística: con ~150 publicaciones, cruzar 4 dimensiones deja
casi todas las celdas con 0-1 posts. Por eso:
  - usamos FRANJAS horarias (no la hora exacta),
  - SIEMPRE mostramos `n` (cuántos posts respaldan cada número),
  - las recomendaciones filtran combos con `n` mínimo.
Las recomendaciones se afinan a medida que la medición diaria acumula datos.
"""
from __future__ import annotations

import pandas as pd


def matrix(df: pd.DataFrame, dim: str, metric: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Matriz `dim` × día: promedio de `metric` y conteo de posts por celda.

    dim: 'formato' o 'tema'. Devuelve (medias, conteos) como DataFrames pivote.
    """
    if df.empty or dim not in df.columns or metric not in df.columns:
        return pd.DataFrame(), pd.DataFrame()
    orden_dias = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    d = df.dropna(subset=[dim, "dia_semana"])
    medias = d.pivot_table(index=dim, columns="dia_semana", values=metric, aggfunc="mean")
    conteos = d.pivot_table(index=dim, columns="dia_semana", values=metric, aggfunc="count")
    cols = [c for c in orden_dias if c in medias.columns]
    return medias.reindex(columns=cols), conteos.reindex(columns=cols)


def best_slots(
    df: pd.DataFrame,
    metric: str = "reach",
    dims: tuple[str, ...] = ("formato", "dia_semana", "franja"),
    min_n: int = 3,
    top: int = 12,
) -> pd.DataFrame:
    """Mejores combinaciones (formato · día · franja) por `metric`.

    Solo devuelve combos con al menos `min_n` publicaciones (para no recomendar
    en base a un único post afortunado). Ordenado de mejor a peor.
    """
    faltan = [c for c in list(dims) + [metric] if c not in df.columns]
    if df.empty or faltan:
        return pd.DataFrame()
    d = df.dropna(subset=list(dims) + [metric])
    g = d.groupby(list(dims)).agg(
        n=(metric, "count"),
        promedio=(metric, "mean"),
    ).reset_index()
    g = g[g["n"] >= min_n].sort_values("promedio", ascending=False)
    g["promedio"] = g["promedio"].round(1)
    return g.head(top)


def slot_hooks(
    df: pd.DataFrame,
    formato: str | None = None,
    dia: str | None = None,
    franja: str | None = None,
    tema: str | None = None,
    metric: str = "saved",
    n: int = 8,
) -> pd.DataFrame:
    """Hooks de las publicaciones que caen en un slot dado, mejores primero."""
    d = df.copy()
    for col, val in [("formato", formato), ("dia_semana", dia),
                     ("franja", franja), ("tema", tema)]:
        if val is not None:
            d = d[d[col] == val]
    if d.empty or metric not in d.columns:
        return pd.DataFrame()
    d = d[d["hook"].str.len() > 0].dropna(subset=[metric])
    cols = [c for c in ["hook", "tema", "formato", "dia_semana", metric] if c in d.columns]
    return d.sort_values(metric, ascending=False).head(n)[cols]


def recommendation_text(df: pd.DataFrame, metric: str = "reach", min_n: int = 3) -> str:
    """Frase resumen con el mejor combo formato·día·franja (o aviso si falta data)."""
    slots = best_slots(df, metric=metric, min_n=min_n, top=1)
    if slots.empty:
        return ("Todavía no hay combinaciones con suficientes publicaciones "
                f"(mínimo {min_n}). Se van a poder recomendar con más datos.")
    r = slots.iloc[0]
    return (f"Mejor combo por {metric}: **{r['formato']} · {r['dia_semana']} · "
            f"{r['franja']}** (promedio {r['promedio']:.0f}, n={int(r['n'])}).")
