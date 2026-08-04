"""Análisis de drivers: qué atributos del creativo mueven el rendimiento.

Feature engineering sobre cada publicación (largo del caption, emojis, presencia
de números/preguntas, hashtags, hora…) + correlaciones y comparación de cuartiles
contra las métricas objetivo (reach_rate, save_rate, share_rate).

Ojo con la interpretación: con pocas publicaciones y guardados/compartidos bajos,
las correlaciones son DIRECCIONALES (señales débiles), no leyes. Sirven para
formar hipótesis que después se validan iterando contenido.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

# Rango amplio de emojis (símbolos, pictogramas, banderas).
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\U00002190-\U000021FF]"
)

# Features numéricas del creativo que analizamos.
FEATURES = [
    "cap_len", "word_count", "n_emojis", "has_question",
    "has_number", "n_hashtags", "hook_len", "hora",
]

# Métricas objetivo por defecto (rendimiento a explicar).
TARGETS = ["reach_rate", "save_rate", "share_rate"]


def add_creative_features(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega columnas de features derivadas del caption/hook. No muta el input."""
    out = df.copy()
    cap = out["caption"].fillna("")
    out["cap_len"] = cap.str.len()
    out["word_count"] = cap.str.split().apply(len)
    out["n_emojis"] = cap.apply(lambda c: len(_EMOJI_RE.findall(c)))
    out["has_question"] = cap.str.contains(r"[¿?]").astype(int)
    out["has_number"] = cap.str.contains(r"\d").astype(int)
    out["n_hashtags"] = cap.str.count("#")
    out["hook_len"] = out["hook"].fillna("").str.len()
    return out


def correlations(df: pd.DataFrame, targets: list[str] | None = None) -> pd.DataFrame:
    """Correlación de Spearman de cada feature contra cada métrica objetivo.

    Devuelve una tabla feature × target. Spearman = robusto a outliers y no exige
    relación lineal (adecuado para métricas con colas largas como el alcance).
    """
    targets = targets or TARGETS
    d = add_creative_features(df)
    cols = [t for t in targets if t in d.columns]
    if not cols:
        return pd.DataFrame()
    result = {}
    for t in cols:
        sub = d[FEATURES + [t]].apply(pd.to_numeric, errors="coerce").dropna(subset=[t])
        if len(sub) < 5:
            continue
        result[t] = sub.corr(method="spearman")[t].drop(t)
    return pd.DataFrame(result).round(2)


def quartile_compare(df: pd.DataFrame, target: str = "reach_rate") -> pd.DataFrame:
    """Compara el cuartil superior vs inferior de `target`: media de cada feature.

    Responde "¿qué tienen en común mis mejores creativos vs los peores?".
    """
    d = add_creative_features(df).dropna(subset=[target])
    if len(d) < 8:
        return pd.DataFrame()
    lo, hi = d[target].quantile([0.25, 0.75])
    top = d[d[target] >= hi]
    bot = d[d[target] <= lo]
    filas = []
    for f in FEATURES:
        filas.append({
            "feature": f,
            "top_25%": round(top[f].mean(), 1),
            "bottom_25%": round(bot[f].mean(), 1),
            "delta": round(top[f].mean() - bot[f].mean(), 1),
        })
    return pd.DataFrame(filas)


def top_quartile_mix(df: pd.DataFrame, target: str = "reach_rate") -> dict:
    """Distribución de formato y tema en el cuartil superior de `target`."""
    d = add_creative_features(df).dropna(subset=[target])
    if len(d) < 8:
        return {}
    hi = d[target].quantile(0.75)
    top = d[d[target] >= hi]
    return {
        "formato": top["formato"].value_counts().to_dict(),
        "tema": top["tema"].value_counts().to_dict(),
    }
