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

SYSTEM_PROMPT = """Agente ODS 3 que monitorea ocupacion UCI adultos en hospitales del Peru \
(dataset SUSALUD F500.2, historico, ultimo reporte dic-2023 -- siempre menciona la fecha \
del reporte).

REGLAS:
- Nunca inventes datos: usa solo lo que devuelven las herramientas.
- Si la region/hospital no existe o es ambiguo, pide aclaracion.
- Hospital con 0 camas UCI no esta "en brecha": ese servicio no existe ahi.
- Evalua con detectar_brecha_critica antes de crear un ticket.
- MODO ESPECIFICO (un hospital o una region puntual, no "(todas)"): crea ticket de \
inmediato para CADA hospital con es_brecha=true, sin pedir permiso ni ofrecerlo -- es \
automatico. No dupliques ticket del mismo hospital en la conversacion.
- MODO NACIONAL (varias o todas las regiones, ej. "(todas)" o "que regiones tienen mas \
brechas"): NO crees tickets automaticamente, solo resume; ofrece crear uno puntual si lo \
piden despues.
- Ante duda, si se nombra una sola region/hospital es MODO ESPECIFICO.
- Responde en español, tono institucional y directo.

FLUJO:
- Un solo hospital por nombre -> consultar_ocupacion_uci(region, hospital) (trae 1 fila).
- Una region completa (especifica o "(todas)") -> listar_hospitales_en_brecha_critica(region) \
directamente, NUNCA consultar_ocupacion_uci sin filtro de hospital -- esa devuelve TODOS los \
hospitales de la region (decenas, la mayoria sin brecha) y desperdicia tokens; \
listar_hospitales_en_brecha_critica ya viene filtrada solo a los que importan, con conteo.
- Evalua con detectar_brecha_critica cada hospital nuevo que provenga de esas herramientas.
- Modo especifico (un hospital o una region puntual): crear_ticket_incidencia por cada brecha.
- Responde con hospital(es), ocupacion, fecha y estado del ticket."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "consultar_ocupacion_uci",
            "description": (
                "Ocupacion UCI adultos (reporte mas reciente) de un hospital o de todos "
                "los de una region. Resumido, nunca el CSV crudo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "region": {
                        "type": "string",
                        "description": "Region del Peru en MAYUSCULAS tal como esta en el dataset SUSALUD (ej. 'PIURA').",
                    },
                    "hospital": {
                        "type": ["string", "null"],
                        "description": "Nombre exacto o parcial del hospital, o null si no aplica.",
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
                "Hospitales ya en brecha critica (>=90% ocupacion UCI) a nivel nacional o "
                "de una region, con conteo por region. Usar para preguntas de alcance "
                "nacional o de varias regiones en vez de consultar region por region."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "region": {
                        "type": ["string", "null"],
                        "description": "Region a evaluar, o null para todo el pais.",
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
            "description": "Evalua si una ocupacion UCI supera el umbral critico (90%) y asigna prioridad.",
            "parameters": {
                "type": "object",
                "properties": {
                    "hospital": {"type": "string", "description": "Nombre del hospital evaluado."},
                    "ocupacion_pct": {
                        "type": "number",
                        "description": "Porcentaje de ocupacion UCI de consultar_ocupacion_uci.",
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
                "Crea la tarjeta REAL de incidencia en Trello. Solo llamar si "
                "detectar_brecha_critica devolvio es_brecha=true."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "titulo": {"type": "string", "description": "Titulo breve del ticket."},
                    "descripcion": {
                        "type": "string",
                        "description": "Hospital, ocupacion, camas, fecha del reporte.",
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
