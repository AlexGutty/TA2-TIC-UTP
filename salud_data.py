"""
Modulo de datos para el agente "Gestor de Brechas de Salud".

Carga el dataset historico del Formato F500.2 de SUSALUD (disponibilidad y
ocupacion de camas UCI de adultos) y expone funciones ya filtradas y
resumidas, para que el modelo de lenguaje nunca reciba el CSV crudo.

El archivo real viene separado por "|" (no por comas) y con bytes nulos
(\\x00) intercalados en cada campo de texto -- un problema de codificacion
del exportador de SUSALUD. Este modulo limpia eso al cargar.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from functools import lru_cache

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

# Ruta del CSV real. Se puede sobreescribir con la variable de entorno
# CAMAS_CSV_PATH si el archivo esta en otro lugar.
CSV_PATH = os.getenv("CAMAS_CSV_PATH", os.path.join(os.path.dirname(__file__), "data", "TB_CAMAS_F500.csv"))

# Umbral de ocupacion UCI a partir del cual se considera "brecha critica".
# Justificado en el plan del proyecto: el promedio real de ocupacion entre
# hospitales con UCI activa es ~57%, asi que 90% es un caso genuinamente
# atipico, no la mitad de los hospitales.
UMBRAL_BRECHA_CRITICA = 90.0

# Credenciales de Trello -- se leen del .env (nunca hardcodeadas).
TRELLO_API_KEY = os.getenv("TRELLO_API_KEY")
TRELLO_TOKEN = os.getenv("TRELLO_TOKEN")
TRELLO_LIST_ID = os.getenv("TRELLO_LIST_ID")
TRELLO_API_URL = "https://api.trello.com/1/cards"

_COLUMNAS_NECESARIAS = [
    "FECHACORTE",
    "CODIGO",
    "NOMBRE",
    "CATEGORIA",
    "NIVEL",
    "REGION",
    "PROVINCIA",
    "DISTRITO",
    "ZC_UCI_ADUL_CAM_TOTAL",
    "ZC_UCI_ADUL_CAM_TOT_DISP",
    "ZC_UCI_ADUL_CAM_TOT_OCUP",
    "ZNC_UCI_ADUL_CAM_TOTAL",
    "ZNC_UCI_ADUL_CAM_DISPONIBLE",
    "ZNC_UCI_ADUL_CAM_OCUPADO",
]


@dataclass
class ResultadoHospital:
    codigo: int
    nombre: str
    region: str
    provincia: str
    distrito: str
    fecha_reporte: str
    camas_operativas: float
    camas_disponibles: float
    camas_ocupadas: float
    ocupacion_pct: float | None  # None si el hospital no tiene UCI de adultos


def _leer_csv_crudo(path: str) -> pd.DataFrame:
    """Lee el CSV tal como lo publica SUSALUD: separado por '|', en latin-1,
    y con bytes nulos (\\x00) pegados a cada valor de texto. El parser de
    pandas no tokeniza bien la fila de encabezado con esos nulos de por
    medio (los confunde y termina con columnas 'Unnamed'), asi que se
    eliminan los bytes nulos del archivo ANTES de pasarselo a pandas,
    trabajando en memoria con un buffer en vez de crear un archivo temporal."""
    with open(path, "rb") as f:
        crudo = f.read()

    limpio = crudo.replace(b"\x00", b"")
    buffer = io.StringIO(limpio.decode("latin1"))

    df = pd.read_csv(
        buffer,
        sep="|",
        usecols=lambda c: c.strip() in _COLUMNAS_NECESARIAS,
        low_memory=False,
    )
    df.columns = [c.strip() for c in df.columns]

    for col in df.select_dtypes(include=["object", "string"]).columns:
        df[col] = df[col].str.strip()

    df["FECHACORTE"] = pd.to_datetime(df["FECHACORTE"], errors="coerce")
    return df


@lru_cache(maxsize=1)
def _dataset_procesado() -> pd.DataFrame:
    """Carga el CSV UNA sola vez por proceso (cacheado), se queda con el
    reporte mas reciente de cada hospital, y calcula la ocupacion de UCI de
    adultos sumando zona COVID y no COVID."""
    df = _leer_csv_crudo(CSV_PATH)

    df = df.sort_values("FECHACORTE")
    latest = df.groupby("CODIGO", as_index=False).last()

    latest["camas_operativas"] = (
        latest["ZC_UCI_ADUL_CAM_TOTAL"].fillna(0) + latest["ZNC_UCI_ADUL_CAM_TOTAL"].fillna(0)
    )
    latest["camas_ocupadas"] = (
        latest["ZC_UCI_ADUL_CAM_TOT_OCUP"].fillna(0) + latest["ZNC_UCI_ADUL_CAM_OCUPADO"].fillna(0)
    )
    latest["camas_disponibles"] = (
        latest["ZC_UCI_ADUL_CAM_TOT_DISP"].fillna(0) + latest["ZNC_UCI_ADUL_CAM_DISPONIBLE"].fillna(0)
    )

    # Ocupacion solo tiene sentido si el hospital tiene UCI de adultos
    # operativa. Los que tienen 0 camas totales no estan "en crisis": ese
    # servicio simplemente no existe en ese establecimiento.
    con_uci = latest["camas_operativas"] > 0
    latest["ocupacion_pct"] = None
    latest.loc[con_uci, "ocupacion_pct"] = (
        latest.loc[con_uci, "camas_ocupadas"] / latest.loc[con_uci, "camas_operativas"] * 100
    ).round(1)

    return latest


def recargar_dataset() -> None:
    """Limpia el cache -- util solo para pruebas o si el CSV se reemplaza
    en caliente. La app normal no necesita llamarla."""
    _dataset_procesado.cache_clear()


# ---------------------------------------------------------------------------
# Las tres funciones que el modelo puede invocar (function calling / tools)
# ---------------------------------------------------------------------------

def consultar_ocupacion_uci(region: str, hospital: str | None = None) -> dict:
    """Consulta el reporte mas reciente de ocupacion de UCI de adultos,
    filtrado por region y opcionalmente por nombre de hospital.

    Devuelve un resumen ya agregado y recortado -- nunca el CSV crudo. Cuando
    se pide una region entera (sin hospital puntual) se omiten los hospitales
    sin UCI de adultos operativa: son ruido para el analisis de brechas y
    infladan mucho la respuesta (ahorra tokens en el modelo).
    """
    df = _dataset_procesado()

    filtro = df["REGION"].str.upper() == region.strip().upper()
    if hospital:
        filtro &= df["NOMBRE"].str.upper().str.contains(hospital.strip().upper(), na=False)
    else:
        filtro &= df["camas_operativas"] > 0

    subset = df[filtro]

    if subset.empty:
        return {
            "encontrado": False,
            "mensaje": f"No se encontraron hospitales para region='{region}'"
            + (f" y hospital='{hospital}'" if hospital else "") + " en el dataset.",
        }

    resultados = []
    for _, row in subset.iterrows():
        resultados.append({
            "nombre": row["NOMBRE"],
            "region": row["REGION"],
            "provincia": row["PROVINCIA"],
            "fecha_reporte": row["FECHACORTE"].strftime("%Y-%m-%d") if pd.notna(row["FECHACORTE"]) else None,
            "camas_operativas": int(row["camas_operativas"]),
            "camas_ocupadas": int(row["camas_ocupadas"]),
            "ocupacion_pct": row["ocupacion_pct"],
        })

    return {"encontrado": True, "total_hospitales": len(resultados), "hospitales": resultados}


# Tope de hospitales individuales devueltos en el listado nacional/regional
# de brechas -- el conteo por region ya da el panorama completo; listar cada
# hospital cuando hay decenas en brecha infla la respuesta muy por encima de
# lo que el modelo necesita para responder (y del limite de tokens por
# minuto de la API).
_TOPE_HOSPITALES_LISTADO = 25


def listar_hospitales_en_brecha_critica(region: str | None = None) -> dict:
    """Recorre TODO el dataset (o una region especifica) en una sola pasada y
    devuelve los hospitales que ya estan en brecha critica (>=90% ocupacion
    UCI adultos), mas un conteo por region.

    Existe para preguntas de alcance nacional o "todas las regiones" -- evita
    que el modelo tenga que llamar consultar_ocupacion_uci region por region
    (24 veces), que es lento y hace que el tool calling de Groq se vuelva
    inestable con este modelo. El listado individual se recorta a los mas
    criticos (_TOPE_HOSPITALES_LISTADO); el conteo por region siempre es
    completo."""
    df = _dataset_procesado()
    con_uci = df[df["camas_operativas"] > 0].copy()

    if region:
        con_uci = con_uci[con_uci["REGION"].str.upper() == region.strip().upper()]

    en_brecha = con_uci[con_uci["ocupacion_pct"] >= UMBRAL_BRECHA_CRITICA].sort_values(
        "ocupacion_pct", ascending=False
    )

    hospitales = [
        {
            "nombre": row["NOMBRE"],
            "region": row["REGION"],
            "ocupacion_pct": row["ocupacion_pct"],
        }
        for _, row in en_brecha.head(_TOPE_HOSPITALES_LISTADO).iterrows()
    ]

    conteo_por_region = (
        en_brecha.groupby("REGION").size().sort_values(ascending=False).to_dict()
    )

    fecha_reporte = (
        con_uci["FECHACORTE"].max().strftime("%Y-%m-%d") if not con_uci.empty and pd.notna(con_uci["FECHACORTE"].max()) else None
    )

    return {
        "total_hospitales_en_brecha": len(en_brecha),
        "total_hospitales_con_uci_evaluados": len(con_uci),
        "fecha_reporte": fecha_reporte,
        "conteo_por_region": conteo_por_region,
        "hospitales_top": hospitales,
        "nota": (
            f"Se muestran los {len(hospitales)} mas criticos de {len(en_brecha)} en brecha; "
            "usa conteo_por_region para el panorama completo."
        ) if len(en_brecha) > len(hospitales) else None,
    }


def detectar_brecha_critica(hospital: str, ocupacion_pct: float) -> dict:
    """Evalua si un porcentaje de ocupacion supera el umbral critico (90%)
    y determina la prioridad de la alerta."""
    if ocupacion_pct is None:
        return {
            "es_brecha": False,
            "motivo": f"{hospital} no tiene UCI de adultos operativa; no aplica evaluacion de brecha.",
        }

    es_brecha = ocupacion_pct >= UMBRAL_BRECHA_CRITICA

    if ocupacion_pct >= 98:
        prioridad = "alta"
    elif ocupacion_pct >= UMBRAL_BRECHA_CRITICA:
        prioridad = "media"
    else:
        prioridad = "baja"

    return {
        "es_brecha": es_brecha,
        "hospital": hospital,
        "ocupacion_pct": ocupacion_pct,
        "umbral": UMBRAL_BRECHA_CRITICA,
        "prioridad": prioridad if es_brecha else None,
    }


# Recuerda los titulos de ticket ya creados en este proceso (una corrida de
# Streamlit), para no duplicar la misma tarjeta si el modelo insiste dos
# veces sobre el mismo hospital en una conversacion.
_tickets_ya_creados: set[str] = set()


def crear_ticket_incidencia(titulo: str, descripcion: str, prioridad: str, region: str) -> dict:
    """Crea una tarjeta real en Trello con los detalles de la brecha critica
    detectada. Esta es la automatizacion visible que se demuestra en vivo."""
    if not all([TRELLO_API_KEY, TRELLO_TOKEN, TRELLO_LIST_ID]):
        return {
            "creado": False,
            "error": "Faltan credenciales de Trello (TRELLO_API_KEY, TRELLO_TOKEN o TRELLO_LIST_ID) en el .env",
        }

    clave = titulo.strip().upper()
    if clave in _tickets_ya_creados:
        return {
            "creado": False,
            "duplicado": True,
            "motivo": f"Ya se creo un ticket con el titulo '{titulo}' antes en esta sesion. No se crea de nuevo.",
        }

    etiqueta_prioridad = {"alta": "\U0001F534", "media": "\U0001F7E1", "baja": "\U0001F7E2"}.get(prioridad, "")

    payload = {
        "key": TRELLO_API_KEY,
        "token": TRELLO_TOKEN,
        "idList": TRELLO_LIST_ID,
        "name": f"{etiqueta_prioridad} [{prioridad.upper()}] {titulo}",
        "desc": f"{descripcion}\n\nRegion: {region}\nPrioridad: {prioridad}",
    }

    try:
        resp = requests.post(TRELLO_API_URL, params=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        _tickets_ya_creados.add(clave)
        return {
            "creado": True,
            "id_ticket": data.get("id"),
            "url_ticket": data.get("shortUrl") or data.get("url"),
        }
    except requests.exceptions.RequestException as e:
        return {"creado": False, "error": str(e)}


if __name__ == "__main__":
    # Prueba rapida por consola: python salud_data.py
    print("Cargando dataset...")
    df = _dataset_procesado()
    print(f"Hospitales unicos en el ultimo reporte: {len(df)}")
    print(f"Fecha mas reciente: {df['FECHACORTE'].max()}")

    print("\n--- Prueba: consultar_ocupacion_uci('LORETO') ---")
    r = consultar_ocupacion_uci("LORETO")
    print(f"Encontrados: {r.get('total_hospitales')}")
    for h in r.get("hospitales", [])[:3]:
        print(f"  {h['nombre']}: {h['ocupacion_pct']}% ocupacion ({h['fecha_reporte']})")

    print("\n--- Prueba: detectar_brecha_critica ---")
    con_uci = df[df["camas_operativas"] > 0].sort_values("ocupacion_pct", ascending=False)
    top = con_uci.iloc[0]
    resultado = detectar_brecha_critica(top["NOMBRE"], top["ocupacion_pct"])
    print(resultado)

    print("\n--- Prueba: crear_ticket_incidencia (crea una tarjeta REAL en Trello) ---")
    ticket = crear_ticket_incidencia(
        titulo=f"Brecha critica UCI - {top['NOMBRE']}",
        descripcion=(
            f"Ocupacion UCI adultos: {top['ocupacion_pct']}% "
            f"({top['camas_ocupadas']:.0f}/{top['camas_operativas']:.0f} camas). "
            f"Fecha del reporte: {top['FECHACORTE'].strftime('%Y-%m-%d')}."
        ),
        prioridad=resultado["prioridad"] or "media",
        region=top["REGION"],
    )
    print(ticket)
