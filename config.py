"""Carga y valida la configuración desde el archivo `.env`.

Un único punto de acceso a las variables de entorno para todo el proyecto.
Importar `settings` desde acá en vez de leer os.environ suelto.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
import os
import sys

# Raíz del proyecto = carpeta que contiene este archivo.
ROOT = Path(__file__).resolve().parent

# Carga .env desde la raíz (si existe). No falla si no está.
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    app_id: str
    app_secret: str
    access_token: str
    user_id: str
    api_version: str
    anthropic_api_key: str
    anthropic_model: str
    db_path: Path
    local_utc_offset: int  # p.ej. -3 = Argentina (sin horario de verano)

    @property
    def graph_base(self) -> str:
        """URL base de la Graph API con la versión configurada."""
        return f"https://graph.instagram.com/{self.api_version}"

    @property
    def local_tz(self) -> timezone:
        """Zona horaria local (offset fijo). La API devuelve todo en UTC; esto
        convierte a hora local para que día/hora de publicación sean accionables.
        Argentina no usa horario de verano, por eso un offset fijo alcanza."""
        return timezone(timedelta(hours=self.local_utc_offset))

    def require(self, *names: str) -> None:
        """Falla con un mensaje claro si falta alguna variable obligatoria.

        Se llama al inicio de los scripts que sí necesitan credenciales,
        para no explotar con errores crípticos de la API más adelante.
        """
        faltan = [n for n in names if not getattr(self, n)]
        if faltan:
            legibles = {
                "app_id": "IG_APP_ID",
                "app_secret": "IG_APP_SECRET",
                "access_token": "IG_ACCESS_TOKEN",
                "user_id": "IG_USER_ID",
                "anthropic_api_key": "ANTHROPIC_API_KEY",
            }
            vars_txt = ", ".join(legibles.get(n, n) for n in faltan)
            raise SystemExit(
                f"\n[config] Faltan variables de entorno: {vars_txt}\n"
                f"          Copiá .env.example a .env y completá esos valores.\n"
                f"          (Para el token largo y el user_id: python scripts/refresh_token.py)\n"
            )


def enable_utf8_console() -> None:
    """Fuerza stdout/stderr a UTF-8 en la consola de Windows.

    Sin esto, imprimir acentos/emojis en una consola cp1252 (default en Windows)
    puede tirar UnicodeEncodeError. Se llama al inicio de los scripts de CLI.
    """
    for stream in ("stdout", "stderr"):
        s = getattr(sys, stream, None)
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass  # stream redirigido o sin reconfigure: seguimos sin romper


def load_settings() -> Settings:
    db_path = Path(os.getenv("DB_PATH", "data/insta.db"))
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    return Settings(
        app_id=os.getenv("IG_APP_ID", "").strip(),
        app_secret=os.getenv("IG_APP_SECRET", "").strip(),
        access_token=os.getenv("IG_ACCESS_TOKEN", "").strip(),
        user_id=os.getenv("IG_USER_ID", "").strip(),
        api_version=os.getenv("IG_API_VERSION", "v23.0").strip(),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5").strip(),
        db_path=db_path,
        local_utc_offset=int(os.getenv("LOCAL_UTC_OFFSET", "-3")),
    )


settings = load_settings()
