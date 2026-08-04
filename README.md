# insta-app

Dashboard de análisis de métricas de Instagram para **@soy.leo_ai** (IA aplicada a arquitectura).

Trae las métricas reales de tu cuenta vía la **Instagram Graph API**, las guarda con histórico,
y las analiza para que puedas ver **qué contenido tracciona** (por formato y por tema) y tomar
decisiones de creación con datos en vez de suposiciones.

> Alcance actual: **lectura de métricas + análisis**. El bot de mensajes, la publicación
> automática y la gestión de Ads son fases posteriores (ver el final de este README).

---

## Qué hace

- Lee métricas de **reels, historias, carruseles y fotos** de tu cuenta.
- Guarda **histórico** en SQLite (la API no da series completas hacia atrás; nosotros las
  construimos capturando snapshots).
- Etiqueta cada publicación por **tema** (asistido por IA, con corrección manual).
- Calcula los **ratios que mira el algoritmo** (reach/save/share rate, breakout).
- **Drivers**: analiza qué atributos del creativo (largo, emojis, números, hora…) mueven el rendimiento.
- **Velocidad**: mide cómo acumula cada post en las primeras 24-48 h (predice si Meta lo empuja).
- Dashboard con: ratios, rendimiento por formato, por tema, rankings, horarios y minería de hooks.
- Exporta un **brief de contenido** que alimenta tu prompt de creación con evidencia real.

---

## Requisitos

- Python 3.12+
- Cuenta de Instagram **profesional** (business o creador).
- App de Meta for Developers con el caso de uso *"Administrar mensajes y contenido en Instagram"*
  (config con **inicio de sesión de Instagram**) y el permiso `instagram_business_manage_insights`
  agregado.

---

## Setup (local)

```bash
# 1. Crear entorno e instalar dependencias
python -m venv .venv
.venv\Scripts\activate        # Windows (PowerShell: .venv\Scripts\Activate.ps1)
pip install -r requirements.txt

# 2. Configurar credenciales
copy .env.example .env         # luego editá .env y pegá App Secret + token corto

# 3. Cambiar el token corto por uno largo (60 días) y descubrir tu user_id
python scripts/refresh_token.py
#    -> pegá en .env los valores IG_ACCESS_TOKEN e IG_USER_ID que imprime

# 4. Traer las métricas
python -m src.fetch

# 5. Abrir el dashboard
streamlit run dashboard/app.py
```

### Cómo obtener el token corto

En el panel de tu app en [developers.facebook.com](https://developers.facebook.com) → caso de uso
de Instagram → **Generar tokens de acceso** → *Agregar cuenta* → iniciás sesión con tu Instagram.
Copiás ese token (de corta duración) a `IG_ACCESS_TOKEN` en `.env`, y el paso 3 lo convierte en
uno de larga duración.

---

## Uso diario

```bash
python -m src.fetch                       # captura un snapshot nuevo de métricas
python scripts/export_content_brief.py    # genera el brief para tu prompt de contenido
streamlit run dashboard/app.py            # explora el dashboard
```

El token largo dura 60 días. Corré `python scripts/refresh_token.py` cada tanto (o el VPS con
cron) para renovarlo antes de que expire.

---

## Estructura

```
config.py                    # carga de variables de entorno
src/ig_client.py             # cliente de la Graph API (manejo defensivo de métricas)
src/db.py                    # SQLite en formato tidy/largo
src/fetch.py                 # orquesta la captura de un snapshot
src/tagging.py               # etiquetado de tema (IA + manual)
src/analysis.py              # agregaciones + ratios + velocidad
src/drivers.py               # feature engineering + correlaciones de drivers
dashboard/app.py             # dashboard Streamlit
scripts/refresh_token.py     # token largo + descubrir user_id
scripts/export_content_brief.py  # brief que alimenta el prompt de contenido
data/insta.db                # base de datos (gitignored)
```

---

## Seguridad

- Las credenciales viven **solo** en `.env` (ignorado por git). Nunca se commitean.
- El token de acceso equivale a una contraseña: no lo pegues en chats ni repos.

---

## Fases siguientes (no incluidas todavía)

- **Bot de mensajes** con IA (MiniMax / Claude) vía webhooks — requiere el VPS con HTTPS público.
- **Publicación automática** de reels/carruseles/historias.
- **Ads**: gestión de campañas vía el MCP oficial de Meta (`mcp.facebook.com/ads`).
- **Despliegue en VPS** con cron diario (para capturar historias antes de que expiren a las 24 h).
