"""Cliente de la Instagram Graph API (configuración *Instagram Login*).

Wrapper delgado sobre `graph.instagram.com`. Se ocupa de:
  - traer datos de la cuenta y las publicaciones
  - traer insights por publicación de forma **resiliente** a los cambios de
    nombres de métricas entre versiones de la API
  - intercambiar/renovar el token de larga duración

Nota sobre métricas: la Graph API rechaza *toda* la llamada de insights si una
sola métrica no está soportada para ese tipo de contenido/versión. Por eso, si
la llamada en lote falla, reintentamos pidiendo cada métrica por separado y nos
quedamos con las que responden. Así el sistema no se rompe cuando Meta cambia la API.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable

import requests

from config import settings


# ── Métricas candidatas por tipo de contenido (media_product_type) ────────────
# Listas amplias: las que no existan en la versión actual se descartan solas.
INSIGHT_METRICS: dict[str, list[str]] = {
    "REELS": [
        "reach", "likes", "comments", "saved", "shares",
        "views", "total_interactions",
        "ig_reels_avg_watch_time", "ig_reels_video_view_total_time",
    ],
    "FEED": [
        "reach", "likes", "comments", "saved", "shares",
        "views", "total_interactions", "profile_visits", "follows",
    ],
    "STORY": [
        "reach", "replies", "shares", "views", "total_interactions",
        "navigation", "profile_visits", "follows",
    ],
    # Fotos/carruseles del feed comparten el set de FEED.
    "CAROUSEL_CONTAINER": [
        "reach", "likes", "comments", "saved", "shares",
        "views", "total_interactions",
    ],
}

# Campos que pedimos de cada publicación. `children` trae los items de un
# carrusel (para poder cachear la miniatura del primero).
MEDIA_FIELDS = (
    "id,caption,media_type,media_product_type,timestamp,permalink,"
    "like_count,comments_count,thumbnail_url,media_url,"
    "children{media_type,media_url,thumbnail_url}"
)

# Campos de la cuenta.
ACCOUNT_FIELDS = (
    "user_id,username,name,account_type,media_count,"
    "followers_count,follows_count,profile_picture_url,biography"
)


class InstagramAPIError(RuntimeError):
    """Error devuelto por la Graph API (con el mensaje original de Meta)."""


@dataclass
class InstagramClient:
    access_token: str = field(default_factory=lambda: settings.access_token)
    user_id: str = field(default_factory=lambda: settings.user_id)
    api_version: str = field(default_factory=lambda: settings.api_version)
    timeout: int = 30
    max_retries: int = 3

    @property
    def _base(self) -> str:
        return f"https://graph.instagram.com/{self.api_version}"

    # ── HTTP interno ─────────────────────────────────────────────────────────
    def _get(self, path: str, params: dict[str, Any] | None = None,
             versioned: bool = True) -> dict:
        """GET con token, reintentos ante errores de red / rate limit."""
        params = dict(params or {})
        params.setdefault("access_token", self.access_token)
        base = self._base if versioned else "https://graph.instagram.com"
        url = f"{base}/{path.lstrip('/')}"

        last_exc: Exception | None = None
        for intento in range(1, self.max_retries + 1):
            try:
                resp = requests.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:  # red caída, DNS, etc.
                last_exc = exc
                time.sleep(min(2 ** intento, 8))
                continue

            if resp.status_code == 200:
                return resp.json()

            # Intentamos extraer el mensaje de error de Meta.
            try:
                err = resp.json().get("error", {})
            except ValueError:
                err = {"message": resp.text}
            code = err.get("code")
            msg = err.get("message", "error desconocido")

            # Rate limit (código 4 / 17 / 32) o 5xx -> reintentar con espera.
            if resp.status_code >= 500 or code in (4, 17, 32, 613):
                last_exc = InstagramAPIError(f"[{resp.status_code}/{code}] {msg}")
                time.sleep(min(2 ** intento, 10))
                continue

            # Error definitivo (token inválido, métrica inválida, etc.).
            raise InstagramAPIError(f"[{resp.status_code}/{code}] {msg}")

        raise InstagramAPIError(f"Falló tras {self.max_retries} intentos: {last_exc}")

    # ── Cuenta ───────────────────────────────────────────────────────────────
    def get_account(self) -> dict:
        """Datos de la cuenta: seguidores, seguidos, cantidad de publicaciones…"""
        target = self.user_id or "me"
        return self._get(target, {"fields": ACCOUNT_FIELDS})

    # ── Publicaciones ────────────────────────────────────────────────────────
    def get_media(self, limit: int | None = None, page_size: int = 50) -> list[dict]:
        """Lista de publicaciones del feed (reels, carruseles, fotos, videos).

        Pagina automáticamente. `limit` corta la cantidad total (None = todas).
        Las historias NO aparecen acá: usar `get_stories()`.
        """
        target = self.user_id or "me"
        out: list[dict] = []
        params: dict[str, Any] = {"fields": MEDIA_FIELDS, "limit": page_size}
        data = self._get(f"{target}/media", params)

        while True:
            out.extend(data.get("data", []))
            if limit is not None and len(out) >= limit:
                return out[:limit]
            next_url = data.get("paging", {}).get("next")
            if not next_url:
                return out
            # `next` es una URL completa con cursor; la pedimos directo.
            data = self._get_next(next_url)

    def _get_next(self, url: str) -> dict:
        for intento in range(1, self.max_retries + 1):
            try:
                resp = requests.get(url, timeout=self.timeout)
                if resp.status_code == 200:
                    return resp.json()
            except requests.RequestException:
                time.sleep(min(2 ** intento, 8))
        return {"data": []}

    def get_stories(self) -> list[dict]:
        """Historias ACTIVAS (solo existen durante 24 h)."""
        target = self.user_id or "me"
        fields = "id,media_type,media_product_type,timestamp,permalink,thumbnail_url,media_url"
        data = self._get(f"{target}/stories", {"fields": fields})
        return data.get("data", [])

    # ── Insights por publicación (resiliente) ────────────────────────────────
    def get_media_insights(self, media_id: str, product_type: str) -> dict[str, float]:
        """Devuelve {metrica: valor} para una publicación.

        Intenta pedir todas las métricas candidatas en una sola llamada. Si la
        API rechaza el lote (alguna métrica no aplica), reintenta métrica por
        métrica y conserva las que sí responden.
        """
        metrics = INSIGHT_METRICS.get(product_type.upper(), INSIGHT_METRICS["FEED"])

        # 1) Intento en lote (camino feliz, 1 sola llamada).
        try:
            data = self._get(f"{media_id}/insights", {"metric": ",".join(metrics)})
            return self._parse_insights(data)
        except InstagramAPIError:
            pass

        # 2) Fallback: una métrica por vez, ignorando las que fallan.
        resultado: dict[str, float] = {}
        for m in metrics:
            try:
                data = self._get(f"{media_id}/insights", {"metric": m})
                resultado.update(self._parse_insights(data))
            except InstagramAPIError:
                continue  # métrica no soportada para este contenido/versión
        return resultado

    @staticmethod
    def _parse_insights(payload: dict) -> dict[str, float]:
        """Extrae {nombre: valor} de la respuesta de insights.

        La API usa dos formas según la métrica: `values[0].value` (series) o
        `total_value.value` (agregados). Cubrimos ambas.
        """
        out: dict[str, float] = {}
        for item in payload.get("data", []):
            name = item.get("name")
            if not name:
                continue
            value = None
            if "total_value" in item and isinstance(item["total_value"], dict):
                value = item["total_value"].get("value")
            elif item.get("values"):
                value = item["values"][0].get("value")
            if isinstance(value, (int, float)):
                out[name] = float(value)
        return out

    # ── Tokens ───────────────────────────────────────────────────────────────
    def exchange_long_lived_token(self, app_secret: str) -> dict:
        """Cambia el token corto por uno de larga duración (~60 días)."""
        return self._get(
            "access_token",
            {
                "grant_type": "ig_exchange_token",
                "client_secret": app_secret,
                "access_token": self.access_token,
            },
            versioned=False,
        )

    def refresh_long_lived_token(self) -> dict:
        """Renueva un token largo que aún no expiró (extiende otros 60 días)."""
        return self._get(
            "refresh_access_token",
            {"grant_type": "ig_refresh_token", "access_token": self.access_token},
            versioned=False,
        )
