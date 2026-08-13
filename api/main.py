"""API backend (FastAPI) — sirve los datos reales al frontend v2.

Envuelve los módulos de `src/` (análisis, planificador, generador) y los expone
como JSON, con las MISMAS formas de datos que usa el frontend. NO mete lógica
nueva. Corre privada en el VPS (Tailscale), como el dashboard.

    uvicorn api.main:app --host <ip-tailscale> --port 8000

Endpoints:
    GET  /api/health
    GET  /api/resumen
    GET  /api/que-funciona
    GET  /api/recomendacion
    GET  /api/hooks
    GET  /api/publicaciones
    GET  /api/timeline
    GET  /api/thumb/{media_id}
    POST /api/generar-guiones
"""
from __future__ import annotations

import re
import time

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config import settings
from src import analysis, guiones, planner

app = FastAPI(title="insta-app API", version="1.0")

# CORS abierto: la API es privada (solo accesible desde la tailnet), así que no
# hace falta restringir orígenes. Si algún día se expone público, acotar acá.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)

TEMA_LABELS = {
    "dolor_tiempo": "Falta de tiempo", "mito_ia": "Mitos de la IA",
    "herramienta_demo": "Herramientas / Cómo se hace",
    "posicionamiento": "Cómo cobrar / posicionarte",
    "motivacional": "Motivación / mindset", "caso_exito": "Casos de éxito",
    "evento": "Eventos / charlas", "dato_estadistica": "Datos y estadísticas",
    "otro": "Otro",
}

# ── Cache liviano de build_dataset (evita reconstruir en cada endpoint) ────────
_CACHE: dict = {"df": None, "ts": 0.0}
_TTL = 300  # 5 min


def get_df() -> pd.DataFrame:
    if _CACHE["df"] is None or (time.time() - _CACHE["ts"]) > _TTL:
        _CACHE["df"] = analysis.build_dataset()
        _CACHE["ts"] = time.time()
    return _CACHE["df"]


def num(v, d=2):
    """Devuelve un número limpio (None si es NaN, para que sea JSON válido)."""
    try:
        f = float(v)
        return round(f, d) if f == f else None
    except (TypeError, ValueError):
        return None


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    df = get_df()
    return {
        "ok": True, "motor": guiones.engine_name(),
        "ultimoDato": str(df["publicado"].max().date()) if not df.empty and df["publicado"].notna().any() else None,
        "seguidores": analysis.latest_followers(), "posts": len(df),
    }


@app.get("/api/resumen")
def resumen():
    df = get_df()
    fs = analysis.followers_series()
    evol = {}
    if not fs.empty:
        for _, r in fs.iterrows():
            if pd.notna(r["followers_count"]):
                evol[str(r["captured_at"].date())] = int(r["followers_count"])
    evolucion = [{"fecha": k, "valor": v} for k, v in sorted(evol.items())]
    seg = analysis.latest_followers()
    return {
        "seguidores": seg,
        "seguidoresHace30Dias": evolucion[0]["valor"] if evolucion else seg,
        "publicaciones": len(df),
        "alcancePromedio": int(num(df["reach"].mean(), 0) or 0),
        "guardadosPromedio": num(df["saved"].mean()),
        "compartidosPromedio": num(df["shares"].mean()),
        "evolucionSeguidores": evolucion,
    }


@app.get("/api/que-funciona")
def que_funciona():
    df = get_df()
    formatos = []
    for fmt, g in df.groupby("formato"):
        formatos.append({
            "nombre": fmt, "publicaciones": int(len(g)),
            "alcance": int(num(g["reach"].mean(), 0) or 0),
            "guardados": num(g["saved"].mean()), "compartidos": num(g["shares"].mean()),
            "avgWatchSeg": (num(g["ig_reels_avg_watch_time"].dropna().mean() / 1000, 1)
                            if "ig_reels_avg_watch_time" in g and g["ig_reels_avg_watch_time"].notna().any()
                            else None),
        })
    formatos = [f for f in formatos if f["nombre"] != "Foto"]
    formatos.sort(key=lambda x: -x["publicaciones"])

    temas = []
    for slug, g in df.groupby("tema"):
        if slug == "sin_etiquetar":
            continue
        reach = num(g["reach"].mean(), 0) or 0
        inter = num(g["interacciones"].mean(), 1) or 0
        temas.append({
            "slug": slug, "nombre": TEMA_LABELS.get(slug, slug), "publicaciones": int(len(g)),
            "alcance": int(reach), "guardados": num(g["saved"].mean()),
            "compartidos": num(g["shares"].mean()), "views": int(num(g["views"].mean(), 0) or 0),
            "likes": num(g["likes"].mean(), 1), "comentarios": num(g["comments"].mean(), 1),
            "interacciones": inter, "engagementRate": num((inter / reach) if reach else 0, 3),
        })
    temas.sort(key=lambda x: -(x["guardados"] or 0))

    top_reach = max(formatos, key=lambda x: x["alcance"]) if formatos else None
    top_save = max(formatos, key=lambda x: (x["guardados"] or 0)) if formatos else None
    concl = "Sin datos suficientes."
    if top_reach and top_save:
        concl = (f"Tus {top_reach['nombre']}s te descubren más gente ({top_reach['alcance']} personas "
                 f"en promedio). Tus {top_save['nombre']}s hacen que te guarden más "
                 f"({top_save['guardados']} por post). Foco: que te guarden y compartan, que es "
                 "lo que el algoritmo premia.")
    return {"formatos": formatos, "temas": temas, "conclusion": concl}


@app.get("/api/recomendacion")
def recomendacion():
    df = get_df()
    slots = planner.best_slots(df, "reach", min_n=3, top=1).to_dict("records")
    if not slots:
        return {"formato": None, "explicacion": "Todavía no hay datos suficientes."}
    s = slots[0]
    conf = "alta" if s["n"] >= 10 else "media" if s["n"] >= 5 else "baja"
    prom = analysis.latest_followers()
    reach_prom = int(num(df["reach"].mean(), 0) or 0)
    return {
        "formato": s["formato"], "dia": s["dia_semana"], "franja": s["franja"],
        "confianza": conf, "n": int(s["n"]),
        "explicacion": (f"Tus {s['formato']}s del {s['dia_semana'].lower()} en la franja "
                        f"{s['franja']} llegaron a {int(s['promedio'])} personas en promedio "
                        f"(sobre {int(s['n'])} publicaciones), más que tu promedio general de {reach_prom}."),
    }


@app.get("/api/hooks")
def hooks(metric: str = "saved", limit: int = 10):
    df = get_df()
    if metric not in df.columns:
        metric = "saved"
    d = df[df["hook"].str.len() > 0].dropna(subset=[metric]).sort_values(metric, ascending=False).head(limit)
    out = []
    for i, (_, r) in enumerate(d.iterrows()):
        out.append({
            "id": f"h{i+1}", "hook": r["hook"], "tema": TEMA_LABELS.get(r["tema"], r["tema"]),
            "formato": r["formato"], "fecha": str(r["publicado"].date()) if pd.notna(r["publicado"]) else "",
            "alcance": int(num(r["reach"], 0) or 0), "guardados": int(num(r["saved"], 0) or 0),
            "compartidos": int(num(r["shares"], 0) or 0), "views": int(num(r["views"], 0) or 0),
            "likes": int(num(r["likes"], 0) or 0), "comentarios": int(num(r["comments"], 0) or 0),
            "interacciones": int(num(r["interacciones"], 0) or 0),
        })
    return out


@app.get("/api/publicaciones")
def publicaciones():
    df = get_df().sort_values("publicado", ascending=False)
    out = []
    for _, r in df.iterrows():
        mid = r["media_id"]
        out.append({
            "id": mid,
            "miniatura": f"/api/thumb/{mid}" if r.get("thumb_local") else None,
            "formato": r["formato"], "temaSlug": r["tema"],
            "tema": TEMA_LABELS.get(r["tema"], r["tema"]),
            "fecha": str(r["publicado"].date()) if pd.notna(r["publicado"]) else "",
            "link": r.get("permalink"),
            "alcance": int(num(r["reach"], 0) or 0), "guardados": int(num(r["saved"], 0) or 0),
            "compartidos": int(num(r["shares"], 0) or 0), "views": int(num(r["views"], 0) or 0),
            "likes": int(num(r["likes"], 0) or 0), "comentarios": int(num(r["comments"], 0) or 0),
            "interacciones": int(num(r["interacciones"], 0) or 0),
            "primeraLinea": r["hook"],
        })
    return out


@app.get("/api/timeline")
def timeline(metric: str = "reach"):
    """Cómo rinde cada formato a lo largo del tiempo (promedio por mes)."""
    df = get_df().dropna(subset=["publicado"]).copy()
    if metric not in df.columns:
        metric = "reach"
    df["mes"] = df["publicado"].dt.strftime("%Y-%m")
    meses = sorted(df["mes"].unique())
    series = []
    for fmt in ["Reel", "Carrusel"]:
        g = df[df["formato"] == fmt]
        valores = []
        for m in meses:
            gm = g[g["mes"] == m]
            valores.append(num(gm[metric].mean(), 2) if len(gm) else None)
        series.append({"formato": fmt, "valores": valores,
                       "posts": [int((g["mes"] == m).sum()) for m in meses]})
    return {"meses": meses, "series": series, "metrica": metric}


@app.get("/api/thumb/{media_id}")
def thumb(media_id: str):
    if not re.fullmatch(r"[0-9]+", media_id):  # solo IDs numéricos (anti path-traversal)
        raise HTTPException(400, "id inválido")
    path = settings.db_path.parent / "thumbs" / f"{media_id}.jpg"
    if not path.exists():
        raise HTTPException(404, "sin miniatura")
    return FileResponse(path, media_type="image/jpeg")


class GenReq(BaseModel):
    objetivo: str = "guardados"
    tema: str | None = None
    formato: str | None = None
    cantidad: int = 2
    notas: str = ""


@app.post("/api/generar-guiones")
def generar(req: GenReq):
    df = get_df()
    if req.objetivo not in guiones.FUNNEL:
        raise HTTPException(400, "objetivo inválido")
    prompt = guiones.build_prompt(req.objetivo, req.tema or None, req.formato or None,
                                  max(1, min(5, req.cantidad)), (req.notas or "").strip(), df)
    try:
        texto = guiones.generate(prompt)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))
    return {"guionesMarkdown": texto, "motor": guiones.engine_name()}
