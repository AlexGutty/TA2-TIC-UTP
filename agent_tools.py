"""
Definicion de herramientas (tools) y prompt de sistema para el agente
"Gestor de Brechas de Salud". Separado de app.py para que la logica de
UI de Streamlit no se mezcle con la definicion del agente.
"""

import json

import salud_data

# Las 24 regiones reales presentes en el dataset de SUSALUD.
REGIONES = [
    "AMAZONAS", "ANCASH", "APURIMAC", "AREQUIPA", "AYACUCHO", "CAJAMARCA",
    "CALLAO", "CUSCO", "HUANCAVELICA", "HUANUCO", "ICA", "JUNIN",
    "LA LIBERTAD", "LAMBAYEQUE", "LIMA", "LORETO", "MADRE DE DIOS",
    "MOQUEGUA", "PASCO", "PIURA", "PUNO", "SAN MARTIN", "TACNA",
    "TUMBES", "UCAYALI",
]

SYSTEM_PROMPT = """Eres un agente de inteligencia artificial especializado en salud publica, \
alineado al ODS 3 (Salud y bienestar). Tu rol es monitorear la ocupacion de camas UCI de \
adultos en hospitales del Peru, usando el dataset historico del Formato F500.2 de SUSALUD \
(Plataforma Nacional de Datos Abiertos del Peru).

OBJETIVOS:
1. Consultar la ocupacion de UCI de adultos de un hospital o de una region cuando el \
usuario lo pida.
2. Evaluar si la ocupacion representa una brecha critica (umbral: 90% o mas).
3. Si se detecta una brecha critica, crear SIEMPRE un ticket de incidencia en Trello con \
los detalles, y confirmarlo claramente al usuario.

REGLAS:
- Nunca inventes datos de ocupacion, nombres de hospitales o porcentajes: usa unicamente \
lo que te devuelvan las herramientas.
- El dataset es historico (el reporte mas reciente disponible es de diciembre de 2023, \
SUSALUD dejo de publicarlo actualizado). Cuando dieras un resultado, menciona la fecha del \
reporte que estas usando para que quien lea sepa que tan vigente es.
- Si una region o un hospital no existe en el dataset, o el nombre es ambiguo, pide \
aclaracion al usuario en vez de asumir.
- Un hospital sin UCI de adultos operativa (0 camas totales) no esta "en crisis": ese \
servicio simplemente no existe ahi. No generes una brecha en ese caso.
- Antes de crear un ticket, siempre evalua primero con detectar_brecha_critica. Si no hay \
brecha, no crees ticket.
- Hay EXACTAMENTE dos modos, y debes distinguirlos por el alcance de la pregunta:
  (a) MODO ESPECIFICO -- el usuario pregunta por UN hospital o UNA sola region (por \
  ejemplo "PIURA", "LORETO", region seleccionada distinta de "(todas)", o un hospital por \
  nombre). En este modo, la creacion de tickets es OBLIGATORIA y AUTOMATICA: por cada \
  hospital que resulte con es_brecha=true, DEBES llamar a crear_ticket_incidencia de \
  inmediato, sin preguntar permiso al usuario ni ofrecerlo como opcion. Nunca digas \
  "puedo crear una alerta si quieres" en este modo: la alerta se crea sola y luego se \
  informa como hecho consumado.
  (b) MODO NACIONAL/COMPARATIVO -- el usuario pide un listado o comparacion de varias o \
  todas las regiones a la vez (por ejemplo region seleccionada = "(todas)", o pregunta \
  "que regiones tienen mas brechas"). Aqui NO se crean tickets automaticamente -- solo \
  se muestra el resumen y el conteo por region, y se ofrece crear el ticket de un \
  hospital especifico si el usuario lo pide despues.
- Si tienes dudas sobre en cual de los dos modos estas, y la pregunta nombra una sola \
region o un solo hospital, trata eso como MODO ESPECIFICO -- el modo nacional es SOLO \
para cuando se piden varias regiones o todas a la vez.
- Tono institucional, claro, directo y empatico. Responde siempre en español.

FLUJO:
1. Recibe la consulta del usuario (region y/o hospital).
2. Si la pregunta es sobre UN hospital o UNA region especifica (MODO ESPECIFICO), llama a \
consultar_ocupacion_uci.
3. Si la pregunta es de alcance nacional o pide comparar varias/todas las regiones (MODO \
NACIONAL/COMPARATIVO; ej. "que regiones tienen mas brechas", region seleccionada = \
"(todas)"), llama UNA sola vez a listar_hospitales_en_brecha_critica en vez de consultar \
region por region -- esto evita tener que hacer muchas llamadas seguidas.
4. Llama a detectar_brecha_critica para cada hospital relevante que provenga de \
consultar_ocupacion_uci (listar_hospitales_en_brecha_critica ya te dice directamente cuales \
estan en brecha, no hace falta evaluarlos de nuevo con esta funcion).
5. Si estas en MODO ESPECIFICO y hay brecha, llama a crear_ticket_incidencia de inmediato \
para cada hospital en brecha -- esto NO es opcional y NO requiere que el usuario lo pida. \
La unica excepcion es no crear mas de un ticket por el mismo hospital en la misma \
conversacion (evita duplicados). Si estas en MODO NACIONAL/COMPARATIVO, NO llames a \
crear_ticket_incidencia a menos que el usuario lo pida explicitamente despues para un \
hospital puntual.
6. Responde con un resumen claro: hospital(es), ocupacion, fecha del reporte, y el estado \
del ticket si se creo uno."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "consultar_ocupacion_uci",
            "description": (
                "Consulta el reporte mas reciente de ocupacion de camas UCI de adultos de "
                "un hospital o de todos los hospitales de una region, sumando zona COVID y "
                "no COVID. Devuelve datos ya filtrados y resumidos, nunca el CSV crudo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "region": {
                        "type": "string",
                        "description": (
                            "Nombre de la region del Peru tal como aparece en el dataset de "
                            f"SUSALUD, en mayusculas (ej. 'PIURA', 'LORETO'). Opciones validas: "
                            f"{', '.join(REGIONES)}."
                        ),
                    },
                    "hospital": {
                        "type": ["string", "null"],
                        "description": "Nombre exacto o parcial del hospital a consultar. Usa null si no se especifica un hospital en particular.",
                    },
                },
                "required": ["region"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_hospitales_en_brecha_critica",
            "description": (
                "Recorre TODO el dataset (o una region especifica) en una sola llamada y "
                "devuelve directamente los hospitales que ya estan en brecha critica (90% o "
                "mas de ocupacion UCI), mas un conteo de cuantos hay por region. USA ESTA "
                "HERRAMIENTA para preguntas de alcance nacional o que comparan varias/todas "
                "las regiones -- nunca llames consultar_ocupacion_uci region por region para "
                "responder ese tipo de pregunta."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "region": {
                        "type": ["string", "null"],
                        "description": "Region especifica a evaluar. Usa null para evaluar TODAS las regiones del pais.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detectar_brecha_critica",
            "description": (
                "Evalua si el porcentaje de ocupacion UCI de un hospital supera el umbral "
                "critico (90%) y determina la prioridad de la alerta."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "hospital": {"type": "string", "description": "Nombre del hospital evaluado."},
                    "ocupacion_pct": {
                        "type": "number",
                        "description": "Porcentaje de ocupacion UCI obtenido de consultar_ocupacion_uci.",
                    },
                },
                "required": ["hospital", "ocupacion_pct"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "crear_ticket_incidencia",
            "description": (
                "Crea una tarjeta de incidencia REAL en el tablero de Trello con los detalles "
                "de la brecha critica detectada. Es la automatizacion visible del sistema: "
                "solo se debe llamar cuando detectar_brecha_critica devolvio es_brecha=true."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "titulo": {"type": "string", "description": "Titulo breve del ticket."},
                    "descripcion": {
                        "type": "string",
                        "description": "Detalle de la brecha: hospital, ocupacion, camas, fecha del reporte.",
                    },
                    "prioridad": {"type": "string", "enum": ["alta", "media", "baja"]},
                    "region": {"type": "string"},
                },
                "required": ["titulo", "descripcion", "prioridad", "region"],
            },
        },
    },
]

# Mapa de nombre de herramienta -> funcion real de salud_data.py
FUNCION_MAP = {
    "consultar_ocupacion_uci": salud_data.consultar_ocupacion_uci,
    "listar_hospitales_en_brecha_critica": salud_data.listar_hospitales_en_brecha_critica,
    "detectar_brecha_critica": salud_data.detectar_brecha_critica,
    "crear_ticket_incidencia": salud_data.crear_ticket_incidencia,
}


def ejecutar_tool_call(tool_call) -> str:
    """Ejecuta la funcion real que corresponde a un tool_call del modelo y
    devuelve el resultado como JSON string, listo para mandarselo de vuelta
    como mensaje de rol 'tool'."""
    nombre = tool_call.function.name
    try:
        argumentos = json.loads(tool_call.function.arguments)
    except json.JSONDecodeError:
        return json.dumps({"error": f"Argumentos invalidos para {nombre}"})

    funcion = FUNCION_MAP.get(nombre)
    if funcion is None:
        return json.dumps({"error": f"Herramienta desconocida: {nombre}"})

    try:
        resultado = funcion(**argumentos)
    except Exception as e:
        resultado = {"error": str(e)}

    return json.dumps(resultado, ensure_ascii=False, default=str)
