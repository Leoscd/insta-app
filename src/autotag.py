"""Auto-etiquetado de tema con NLP local (sin API, sin intervención).

Entrena un clasificador de texto (TF-IDF + SVM lineal) con las publicaciones ya
etiquetadas y predice el tema de las que faltan. Corre dentro de `fetch`, así
cada captura etiqueta lo nuevo automáticamente.

- No necesita API key ni conexión: todo local.
- Aprende de `topic_manual` (tus correcciones) por encima de `topic`.
- Mejora a medida que se acumulan más publicaciones etiquetadas.
- Unas pocas reglas de alta precisión cubren clases raras y fáciles de detectar
  por palabra clave (ej. eventos), donde el ML tiene pocos ejemplos.

Uso manual (además reporta la precisión estimada por validación cruzada):
    python -m src.autotag
"""
from __future__ import annotations

import re

import pandas as pd

from src.db import get_connection, set_topic

# Reglas de alta precisión para clases raras / muy detectables por keyword.
_EVENTO = re.compile(
    r"expocon|f[oó]rum|forum|\bcharla\b|nos vemos|sheraton|congreso|"
    r"semana .*dise[nñ]o|meetup|workshop presencial",
    re.IGNORECASE,
)


def _rule(caption: str) -> str | None:
    """Override por reglas antes del ML. Devuelve tema o None."""
    if caption and _EVENTO.search(caption):
        return "evento"
    return None


def _load() -> pd.DataFrame:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT media_id, caption, topic, topic_manual FROM media"
        ).fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        return df
    # Etiqueta de entrenamiento: la corrección manual manda sobre la automática.
    df["label"] = df["topic_manual"].fillna(df["topic"])
    return df


def train_and_tag(min_train: int = 30, silent: bool = False) -> int:
    """Entrena con lo etiquetado y auto-etiqueta lo pendiente. Devuelve cuántas."""
    def log(msg: str) -> None:
        if not silent:
            print(msg)

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.pipeline import Pipeline
        from sklearn.svm import LinearSVC
    except ImportError:
        log("[autotag] scikit-learn no instalado; salteo el auto-etiquetado "
            "(pip install scikit-learn).")
        return 0

    df = _load()
    if df.empty:
        return 0

    train = df[df["label"].notna() & (df["label"] != "sin_etiquetar")]
    # Pendientes = sin topic NI topic_manual.
    pend = df[df["topic"].isna() & df["topic_manual"].isna()]
    if pend.empty:
        log("[autotag] no hay publicaciones pendientes de etiquetar.")
        return 0
    if len(train) < min_train:
        log(f"[autotag] pocos ejemplos etiquetados ({len(train)}); "
            "salteo hasta tener más.")
        return 0

    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)),
        ("clf", LinearSVC(class_weight="balanced")),
    ])
    pipe.fit(train["caption"].fillna(""), train["label"])

    n = 0
    with get_connection() as conn:
        for _, r in pend.iterrows():
            cap = r["caption"] or ""
            tema = _rule(cap) or (pipe.predict([cap])[0] if cap.strip() else "otro")
            set_topic(conn, r["media_id"], auto=str(tema))
            n += 1
    log(f"[autotag] {n} publicaciones etiquetadas automáticamente.")
    return n


def cross_val_report() -> None:
    """Estima la precisión del clasificador por validación cruzada (para inspección)."""
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.model_selection import cross_val_score
        from sklearn.pipeline import Pipeline
        from sklearn.svm import LinearSVC
    except ImportError:
        print("[autotag] scikit-learn no instalado.")
        return
    df = _load()
    train = df[df["label"].notna() & (df["label"] != "sin_etiquetar")]
    if len(train) < 30:
        print("[autotag] pocos datos para validación cruzada.")
        return
    # Solo clases con >=5 ejemplos, para que el CV tenga sentido.
    counts = train["label"].value_counts()
    usables = counts[counts >= 5].index
    sub = train[train["label"].isin(usables)]
    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)),
        ("clf", LinearSVC(class_weight="balanced")),
    ])
    scores = cross_val_score(pipe, sub["caption"].fillna(""), sub["label"], cv=5)
    print(f"[autotag] precisión estimada (5-fold, clases con >=5 ejemplos): "
          f"{scores.mean():.0%} ± {scores.std():.0%}")
    print(f"[autotag] clases evaluadas: {list(usables)}")


def main() -> None:
    from config import enable_utf8_console
    enable_utf8_console()
    cross_val_report()
    train_and_tag()


if __name__ == "__main__":
    main()
