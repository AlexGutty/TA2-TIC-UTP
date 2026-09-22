# Gestor de Brechas de Salud — Tarea Académica 2 (Herramientas de Desarrollo Profesional TIC)

Chatbot con agente de IA que monitorea la ocupación de camas UCI de adultos en hospitales del Perú y, cuando detecta una brecha crítica (90% de ocupación o más), crea automáticamente un ticket de incidencia en Trello. Está alineado al ODS 3 (Salud y bienestar) y usa datos reales de SUSALUD publicados en la Plataforma Nacional de Datos Abiertos.

La idea del proyecto no era solo simular la automatización en un reporte, sino que funcione de verdad: el usuario pregunta por un hospital o una región desde el chat (por texto o por voz), el agente consulta los datos, evalúa si hay una brecha y, si la hay, genera la alerta en Trello sin que nadie tenga que hacerlo a mano.

## Qué hace el agente

- Consulta la ocupación UCI de un hospital puntual o de todos los hospitales de una región.
- Hace un barrido nacional (o por región) para listar de una sola vez todos los hospitales que ya están en brecha crítica, con el conteo por región.
- Evalúa cada caso contra el umbral crítico y le asigna una prioridad.
- Crea el ticket real en Trello cuando corresponde, evitando duplicados si el mismo hospital ya fue alertado en la conversación.

## Stack

Streamlit para la interfaz (con entrada por texto y voz), Groq (`openai/gpt-oss-20b`) para el function/tool calling, pandas para filtrar el CSV en el backend —el modelo nunca ve el archivo crudo, solo los resultados ya procesados— y la API de Trello para crear las tarjetas.

## Antes de correrlo

### 1. Variables de entorno

Copia `.env.example` como `.env` y completa:

```
GROQ_API_KEY=tu_clave_de_groq
TRELLO_API_KEY=tu_api_key_de_trello
TRELLO_TOKEN=tu_token_de_trello
TRELLO_LIST_ID=id_de_la_lista_donde_se_crean_los_tickets
```

`TRELLO_LIST_ID` es el id de la lista del tablero (por ejemplo "Incidencias detectadas") donde quieres que caigan las tarjetas nuevas.

### 2. Conseguir el dataset

El CSV con el histórico de camas pesa cerca de 280 MB, así que no está subido a este repo (está en `.gitignore`). Hay que descargarlo aparte:

1. Entra al dataset en la Plataforma Nacional de Datos Abiertos: https://www.datosabiertos.gob.pe/dataset/data-hist%C3%B3rica-del-registro-de-camas-diarias-disponibles-y-ocupadas
2. Ahí vas a ver tres recursos. Descárgalos los tres:
   - **Data histórica del Registro de Camas... F500.2 - V.2** → el CSV principal (botón "Ir al recurso", te manda a un servidor del MINSA).
   - **DEFINICIONES OPERACIONALES** → PDF que explica qué significa cada campo.
   - **Diccionario de datos - camas** → Excel con el detalle de las columnas.
3. Crea una carpeta `data/` en la raíz del proyecto y mete ahí los tres archivos.
4. Renombra el CSV a `TB_CAMAS_F500.csv` (así lo busca el código por defecto). Si prefieres dejarlo con otro nombre o en otra ruta, define la variable `CAMAS_CSV_PATH` en tu `.env` apuntando al archivo.

Los otros dos archivos (PDF y Excel) son solo de referencia para entender el dataset, no los lee el código.

### 3. Instalar dependencias

```
pip install streamlit groq python-dotenv pandas requests
```

### 4. Correr la app

```
streamlit run app.py
```

Desde el sidebar puedes elegir la región a monitorear; si no seleccionas ninguna, el agente asume que la pregunta puede ser de cualquier región y lo deduce del mensaje.
