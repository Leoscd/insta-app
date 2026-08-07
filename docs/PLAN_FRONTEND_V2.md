# Plan: rediseño del frontend (v2) — de Streamlit a producto

> **Para el colaborador/agente que toma este trabajo.** Leé todo antes de empezar.
> El dueño (Leo, @soy.leo_ai) revisa por PR. Trabajá en la rama `feat/frontend-v2`.

## 1. Contexto y objetivo

Esta app analiza las métricas de Instagram de un consultor y **genera guiones de
contenido con estrategia de crecimiento**. Hoy el frontend es **Streamlit** y "se ve muy
Streamlit": técnico, poco amigable.

**Objetivo del rediseño:** un frontend **intuitivo y amigable**, que **cualquier persona no
técnica entienda de un vistazo**. Leo lo va a **usar en sus mentorías y compartir con su
comunidad**, así que tiene que verse como un producto, no como un dashboard de data science.

**Principios (no negociables):**
- **Lenguaje humano, cero jerga.** Ver el glosario en la sección 6. Nada de "reach rate",
  "engagement", "correlación de Spearman" en la UI.
- **Gráficas simples.** Barras, números grandes, comparaciones claras. **Nada de heatmaps de
  correlación ni tablas densas** en la vista principal (si se conservan, van detrás de un
  "modo avanzado").
- **Una acción clara por pantalla.** El usuario nunca se pregunta "¿y ahora qué hago?".
- **Mobile-first.** Leo y su comunidad lo van a abrir del celular.
- **Marca:** negro + dorado (`#C4981F`), estilo limpio y premium, pero **más cálido y amigable**
  que el dashboard actual. Soportar tema claro y oscuro.

## 2. Qué NO tocar (el backend ya funciona)

La **lógica de negocio está probada y desplegada**. NO la reescribas. Toda vive en `src/`:

| Módulo | Qué hace |
|---|---|
| `src/analysis.py` | Métricas, ratios, por formato/tema, ranking, horarios, hooks, velocidad |
| `src/planner.py` | Qué publicar / qué día / qué franja (mejores combos) |
| `src/guiones.py` | **Generador de guiones** (`build_prompt`, `generate`, `FUNNEL`) — motor MiniMax/Claude |
| `src/drivers.py` | Análisis de atributos (avanzado, opcional en la UI) |
| `src/fetch.py` | Captura de datos (corre por cron, no lo toques) |

Los datos están en **SQLite** (`data/insta.db`), poblados por el cron 2×/día. Las miniaturas
están cacheadas en `data/thumbs/{media_id}.jpg`.

**Lo único que se reemplaza es `dashboard/app.py` (Streamlit).**

## 3. Arquitectura propuesta

Separar en dos capas limpias:

```
[ Frontend nuevo (SPA amigable) ]  ←  HTTP/JSON  →  [ API (FastAPI) ]  →  src/*.py  →  SQLite
```

1. **API (FastAPI)** — nueva, fina: envuelve las funciones de `src/` y las expone como JSON.
   Va en `api/main.py`. NO mete lógica nueva; solo llama a `analysis`/`planner`/`guiones` y
   serializa. (FastAPI ya es fácil de servir con uvicorn, que ya está instalado.)
2. **Frontend** — SPA moderna. **Recomendado: React + Vite** (o Next.js) con Tailwind. Sin
   framework pesado. Va en `web/`. Consume la API. Buildeás a estáticos.

> Por qué así: desacopla el look del backend, le da libertad total de diseño al frontend, y deja
> la lógica (ya probada) intacta. Si preferís otro stack de frontend, proponelo en el PR con
> justificación — lo que importa es el resultado (amigable, simple, mobile-first).

## 4. Contrato de API (lo que el frontend consume)

Implementar en `api/main.py`. Todas devuelven JSON. Ejemplos de shape:

- `GET /api/health` → `{ "ok": true, "motor": "MiniMax", "ultimo_dato": "2026-08-06", "seguidores": 449, "posts": 155 }`

- `GET /api/resumen` →
  ```json
  { "seguidores": 449, "evolucion_seguidores": [{"fecha":"2026-08-04","valor":448}],
    "publicaciones": 155, "personas_alcanzadas_promedio": 160,
    "guardados_promedio": 0.4, "compartidos_promedio": 0.2 }
  ```

- `GET /api/que-funciona` → rendimiento por formato y por tema, ya en lenguaje simple:
  ```json
  { "formatos": [{"nombre":"Carrusel","publicaciones":35,"alcance":100,"guardados":0.66,"compartidos":0.26}],
    "temas": [{"nombre":"Casos de éxito","publicaciones":3,"guardados":1.0,"compartidos":0.67}] }
  ```
  (Nota: traducir los slugs de tema a nombres lindos — ver glosario.)

- `GET /api/que-publicar?objetivo=alcance|guardados|compartidos` →
  ```json
  { "recomendacion": {"formato":"Reel","dia":"Lunes","franja":"Mediodía","confianza":"alta","n":15},
    "explicacion": "Los reels al mediodía del lunes son los que más te descubren." }
  ```
  (Usa `planner.best_slots` / `recommendation_text`.)

- `GET /api/publicaciones?formato=&orden=alcance|guardados` → galería (excluir fotos):
  ```json
  [{"id":"123","miniatura":"/api/thumb/123","formato":"Reel","tema":"Herramienta",
    "link":"https://instagram.com/...","alcance":627,"guardados":1,"compartidos":4,
    "primera_linea":"¿10 horas semanales de vuelta en tu agenda?"}]
  ```

- `GET /api/thumb/{id}` → sirve `data/thumbs/{id}.jpg` (image/jpeg).

- `POST /api/generar-guiones` — **la función estrella**. Body:
  ```json
  { "objetivo":"guardados", "tema":null, "formato":null, "cantidad":2, "notas":"" }
  ```
  Respuesta: `{ "guiones_markdown": "### Guion...", "motor": "MiniMax" }`
  (Llama a `guiones.build_prompt` + `guiones.generate`. Puede tardar 10-40s → el frontend
  muestra un estado de carga lindo, no una pantalla congelada.)

Opcional / modo avanzado: `GET /api/drivers`, `GET /api/velocidad/{id}`.

## 5. Pantallas a construir (con su intención)

Ordenadas por importancia. Cada una: **un título humano + una sola acción clara**.

1. **Inicio** — "¿Cómo venís?" Números grandes y amables: seguidores (con flechita si subió/bajó),
   cuánta gente te ve en promedio, cuánto te guardan. 1 gráfico simple de evolución de seguidores.
2. **✍️ Crear guion** (la estrella, la que se vende) — El usuario elige en lenguaje simple:
   *¿Qué querés lograr?* (Que me descubran / Que me guarden / Que me compartan), tema, y "Crear".
   Muestra el guion lindo, con botón de copiar y descargar. Estado de carga atractivo.
3. **¿Qué publico?** — La recomendación del planificador en una frase: *"Publicá un Reel el lunes
   al mediodía"*, con el por qué en simple. Nada de matrices densas.
4. **Mis publicaciones** — Galería tipo Instagram (miniaturas), ordenable por "las que más te
   vieron / guardaron / compartieron". Cada una linkea al post real.
5. **¿Qué te funciona?** — Comparación simple formato vs formato y tema vs tema, en barras. Una
   conclusión escrita arriba: *"Tus carruseles se guardan más; tus reels llegan a más gente."*
6. *(Avanzado, opcional/oculto)* — Drivers, velocidad, correlaciones para quien quiera profundizar.

## 6. Glosario: término técnico → lenguaje humano (USAR EN TODA LA UI)

| No decir (técnico) | Decir (humano) |
|---|---|
| Reach / Alcance | "Personas que te vieron" |
| Reach rate | "Qué parte de tu audiencia te ve" |
| Saves / Guardados | "Gente que lo guardó para después" |
| Shares / Compartidos | "Gente que se lo mandó a alguien" |
| Engagement rate | "Qué tan activa reacciona tu gente" |
| Breakout | "Posts que salieron más allá de tus seguidores" |
| Impressions / Views | "Veces que se mostró" |
| `herramienta_demo` | "Herramientas / Cómo se hace" |
| `caso_exito` | "Casos de éxito" |
| `dolor_tiempo` | "Falta de tiempo" |
| `mito_ia` | "Mitos de la IA" |
| `posicionamiento` | "Cómo cobrar / posicionarte" |
| `dato_estadistica` | "Datos y estadísticas" |
| Franja "Mediodía (12-15)" | "Al mediodía" |
| n=15 (tamaño de muestra) | "confianza alta" (n≥10) / "media" (5-9) / "baja / a probar" (<5) |

## 7. Restricciones y hosting (IMPORTANTE, leer)

- **Hoy** el dashboard es **privado en la red Tailscale** de Leo, monousuario (lee SU cuenta).
- **Para venderlo a la comunidad hay que decidir el modelo**, y es una fase aparte del rediseño:
  - **v2a (este plan):** reskin lindo + API, sigue siendo la cuenta de Leo, para demos/mentorías.
  - **v2b (fase futura, NO en este plan):** multi-usuario real (cada cliente conecta SU Instagram
    por OAuth, sus propios datos, login/auth, hosting público con HTTPS, quizás cobro). Eso es un
    salto grande (multi-tenant + auth + onboarding). **Dejarlo anotado, no construirlo todavía.**
- El VPS **no tiene sudo sin contraseña**; para exponer público (nginx/dominio) coordinar con Leo,
  o usar **Tailscale Serve/Funnel**. Para v2a, servir por Tailscale como ahora está bien.

## 8. Cómo trabajar y criterios de aceptación

- Rama **`feat/frontend-v2`**. PRs chicos y frecuentes. Leo/su asistente revisan.
- **No romper el backend** (`src/`, cron, generador). La app vieja de Streamlit puede quedar hasta
  que la nueva esté lista.
- **Definición de "listo" (v2a):**
  - [ ] API FastAPI con todos los endpoints de la sección 4, andando en el VPS.
  - [ ] Frontend nuevo que cubre las pantallas 1-5, **mobile-first**, con la marca negro/dorado.
  - [ ] **Cero jerga**: todo el texto pasa el glosario de la sección 6.
  - [ ] El generador de guiones funciona end-to-end desde la UI, con estado de carga lindo.
  - [ ] Una persona no técnica entiende cada pantalla sin explicación (test con alguien real).
  - [ ] Se sirve en el VPS de forma estable (systemd/cron, sin depender de una sesión SSH).
  - [ ] README de cómo levantar API + frontend en local y en el VPS.

## 9. Arranque rápido (para el agente)

1. Cloná el repo, leé `README.md` y `src/analysis.py`, `src/guiones.py` para entender los datos.
2. Levantá la data local: pedile a Leo el `.env` (o corré contra una copia de `data/insta.db`).
3. Empezá por la **API** (`api/main.py`) — es el contrato. Verificá cada endpoint con curl.
4. Después el **frontend** (`web/`). Empezá por "Crear guion" (pantalla 2), es la que más vende.
5. Preguntá lo que no esté claro en el PR. Leo prioriza: **simple y amigable > completo**.
