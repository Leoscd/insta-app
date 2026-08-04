"""Gestión del token de acceso de larga duración.

Uso típico (primera vez):
    1. Pegá el token CORTO en IG_ACCESS_TOKEN dentro de .env
    2. Ejecutá:  python scripts/refresh_token.py
    3. Pegá en .env los valores IG_ACCESS_TOKEN e IG_USER_ID que imprime

El script detecta solo si tu token es corto (lo intercambia por uno largo de
~60 días) o si ya es largo (lo renueva por otros 60). Además descubre el
`user_id` de la cuenta y lo muestra para que lo guardes.

Nota: el token no se escribe solo en .env a propósito — que lo pegues vos evita
sorpresas y deja el control del secreto en tus manos.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Permite ejecutar el script directo (agrega la raíz del proyecto al path).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import ROOT, enable_utf8_console, settings  # noqa: E402
from src.ig_client import InstagramAPIError, InstagramClient  # noqa: E402


def _update_env(token: str, user_id: str | None) -> None:
    """Reescribe IG_ACCESS_TOKEN (e IG_USER_ID) en el .env, preservando el resto.

    Se usa con --write para que el cron mensual renueve el token sin intervención.
    """
    env_path = ROOT / ".env"
    if not env_path.exists():
        print(f"[token] No existe {env_path}; no se puede escribir.", file=sys.stderr)
        return
    lineas = env_path.read_text(encoding="utf-8").splitlines()
    nuevas: list[str] = []
    visto_token = visto_user = False
    for ln in lineas:
        if ln.startswith("IG_ACCESS_TOKEN="):
            nuevas.append(f"IG_ACCESS_TOKEN={token}"); visto_token = True
        elif ln.startswith("IG_USER_ID=") and user_id:
            nuevas.append(f"IG_USER_ID={user_id}"); visto_user = True
        else:
            nuevas.append(ln)
    if not visto_token:
        nuevas.append(f"IG_ACCESS_TOKEN={token}")
    if user_id and not visto_user:
        nuevas.append(f"IG_USER_ID={user_id}")
    env_path.write_text("\n".join(nuevas) + "\n", encoding="utf-8")
    print(f"[token] .env actualizado ({env_path}).")


def main() -> None:
    enable_utf8_console()
    parser = argparse.ArgumentParser(description="Renueva el token de larga duración.")
    parser.add_argument("--write", action="store_true",
                        help="Reescribe el .env automáticamente (para el cron).")
    args = parser.parse_args()

    settings.require("app_secret", "access_token")
    client = InstagramClient()

    # 1) Conseguir/renovar el token largo.
    #    Intentamos primero el intercambio (funciona si el token es corto).
    #    Si Meta responde que ya es largo, caemos al refresh.
    print("[token] Gestionando token de larga duración…")
    nuevo_token = None
    expira = None
    try:
        data = client.exchange_long_lived_token(settings.app_secret)
        nuevo_token = data.get("access_token")
        expira = data.get("expires_in")
        print("[token] Token corto -> largo: OK")
    except InstagramAPIError as exc:
        print(f"[token] Intercambio no aplicó ({exc}). Probando renovación…")
        try:
            data = client.refresh_long_lived_token()
            nuevo_token = data.get("access_token")
            expira = data.get("expires_in")
            print("[token] Token largo renovado: OK")
        except InstagramAPIError as exc2:
            print(f"[token] ERROR: no se pudo intercambiar ni renovar: {exc2}",
                  file=sys.stderr)
            raise SystemExit(1)

    # 2) Descubrir el user_id con el token nuevo.
    user_id = settings.user_id
    try:
        probe = InstagramClient(access_token=nuevo_token)
        cuenta = probe.get_account()
        user_id = str(cuenta.get("user_id") or cuenta.get("id") or user_id)
        print(f"[token] Cuenta: @{cuenta.get('username')} (user_id {user_id})")
    except InstagramAPIError as exc:
        print(f"[token] (aviso) no se pudo leer el user_id automáticamente: {exc}")

    dias = f"{int(expira) // 86400} días" if expira else "~60 días"

    # 3) Escribir el .env (modo automático) o mostrar qué pegar (modo manual).
    if args.write:
        _update_env(nuevo_token, user_id or None)
        print(f"[token] Renovado OK. Válido ~{dias}.")
    else:
        print("\n" + "=" * 64)
        print("Pegá estos valores en tu archivo .env:\n")
        print(f"IG_ACCESS_TOKEN={nuevo_token}")
        if user_id:
            print(f"IG_USER_ID={user_id}")
        print(f"\n(Token válido ~{dias}. Volvé a correr esto antes de que expire, "
              "o usá --write para que actualice el .env solo.)")
        print("=" * 64)


if __name__ == "__main__":
    main()
