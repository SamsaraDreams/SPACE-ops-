"""Acceso a la hoja VENTAS SPACE 2.0.

Esta capa sabe de celdas y colores; no sabe de negocio. Las decisiones
(que estado sigue, que columna es cual) viven en reglas.py.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from functools import lru_cache

import reglas as R

# Las librerias de Google se importan dentro de las funciones que las usan.
# Asi este modulo se puede importar (y probar con una hoja simulada) en una
# maquina que todavia no las tiene instaladas.

ALCANCES = ["https://www.googleapis.com/auth/spreadsheets"]

# Pestanas que el servidor nunca debe tocar.
PESTANAS_PROTEGIDAS = {
    "DIC 24 Y 2025", "DETALLES 2025", "VENTAS PERLA", "RIFA SPACE", "GASTOS",
}


class ErrorDeHoja(RuntimeError):
    """Fallo al hablar con Google. Distinto de una violacion de regla."""


def _credenciales():
    try:
        from google.oauth2.credentials import Credentials
    except ImportError as e:
        raise ErrorDeHoja(
            "Faltan las librerias de Google. Instalalas con: "
            "pip install google-api-python-client google-auth "
            "google-auth-oauthlib"
        ) from e

    ruta = os.environ.get("GOOGLE_TOKEN_PATH", "").strip()
    if not ruta:
        raise ErrorDeHoja(
            "Falta GOOGLE_TOKEN_PATH. Declaralo en el bloque env del "
            "servidor MCP dentro de config.yaml."
        )
    if not os.path.exists(ruta):
        raise ErrorDeHoja(f"No existe el archivo de credenciales: {ruta}")
    return Credentials.from_authorized_user_file(ruta, ALCANCES)


@lru_cache(maxsize=1)
def _servicio():
    try:
        from googleapiclient.discovery import build
    except ImportError as e:
        raise ErrorDeHoja(
            "Faltan las librerias de Google. Instalalas con: "
            "pip install google-api-python-client google-auth "
            "google-auth-oauthlib"
        ) from e
    try:
        return build("sheets", "v4", credentials=_credenciales(),
                     cache_discovery=False)
    except ErrorDeHoja:
        raise
    except Exception as e:  # noqa: BLE001
        raise ErrorDeHoja(f"No pude conectar con Google Sheets: {e}") from e


def _id_hoja() -> str:
    valor = os.environ.get("SHEET_ID", "").strip()
    if not valor:
        raise ErrorDeHoja("Falta SHEET_ID en el entorno del servidor.")
    return valor


def _cita(pestana: str) -> str:
    """Las pestanas con espacios necesitan comillas en notacion A1."""
    return f"'{pestana}'"


def _comprobar_permitida(pestana: str) -> None:
    """Rechaza pestanas historicas o de configuracion.

    La comparacion es insensible a acentos y mayusculas, igual que
    el resto de comparaciones de encabezados en reglas.py.
    """
    normalizada = R.sin_acentos(pestana)
    if any(normalizada == R.sin_acentos(p) for p in PESTANAS_PROTEGIDAS):
        raise R.ErrorDeRegla(
            f"La pestana '{pestana}' es historica y no se modifica desde aqui."
        )


# --------------------------------------------------------------------------
# Lectura
# --------------------------------------------------------------------------

def listar_pestanas() -> list[str]:
    try:
        meta = _servicio().spreadsheets().get(
            spreadsheetId=_id_hoja(),
            fields="sheets.properties(title,sheetId)",
        ).execute()
    except Exception as e:
        raise ErrorDeHoja(f"No pude leer la lista de pestanas: {e}") from e
    return [s["properties"]["title"] for s in meta.get("sheets", [])]


@lru_cache(maxsize=32)
def _gid(pestana: str) -> int:
    """El id numerico de la pestana, que batchUpdate necesita.

    Se cachea por nombre exacto. Si la pestana no existe, falla rapido
    con un mensaje claro en lugar de llegar hasta el batchUpdate de Google.
    """
    meta = _servicio().spreadsheets().get(
        spreadsheetId=_id_hoja(),
        fields="sheets.properties(title,sheetId)",
    ).execute()
    for s in meta.get("sheets", []):
        if s["properties"]["title"] == pestana:
            return int(s["properties"]["sheetId"])
    raise ErrorDeHoja(
        f"No existe la pestana '{pestana}'. "
        "Verifica el nombre exacto con diagnostico()."
    )


def leer_valores(pestana: str, rango: str) -> list[list]:
    """Devuelve los valores de un rango como lista de filas."""
    try:
        resp = _servicio().spreadsheets().values().get(
            spreadsheetId=_id_hoja(),
            range=f"{_cita(pestana)}!{rango}",
            valueRenderOption="UNFORMATTED_VALUE",
            dateTimeRenderOption="FORMATTED_STRING",
        ).execute()
    except Exception as e:
        raise ErrorDeHoja(f"No pude leer {pestana}!{rango}: {e}") from e
    return resp.get("values", [])


def leer_colores(pestana: str, rango: str) -> list[list[dict | None]]:
    """Devuelve el color de fondo de cada celda del rango.

    Esto es lo que el skill de Google Workspace de Hermes no hace, y es
    justo el dato que lleva el estado de cada pedido.

    Se piden AMBOS formatos (userEntered y effective) y se usa userEntered
    como fuente de verdad —es el que se escribe con pintar_celda—, cayendo
    al effective solo si userEntered viene vacio. Patron del repo de referencia:
    hay celdas cuyo color heredado del tema no aparece en userEntered pero
    si en effectiveFormat.
    """
    try:
        resp = _servicio().spreadsheets().get(
            spreadsheetId=_id_hoja(),
            ranges=[f"{_cita(pestana)}!{rango}"],
            includeGridData=True,
            fields=(
                "sheets.data.rowData.values.userEnteredFormat.backgroundColor,"
                "sheets.data.rowData.values.effectiveFormat.backgroundColor"
            ),
        ).execute()
    except Exception as e:
        raise ErrorDeHoja(f"No pude leer los colores de {pestana}: {e}") from e

    hojas = resp.get("sheets", [])
    if not hojas:
        return []
    datos = hojas[0].get("data", [])
    if not datos:
        return []

    filas: list[list[dict | None]] = []
    for fila in datos[0].get("rowData", []):
        celdas = []
        for celda in fila.get("values", []):
            # userEnteredFormat es el que pintamos nosotros; effectiveFormat
            # incluye herencia del tema. Se prefiere el primero.
            fmt_ue = (celda.get("userEnteredFormat") or {}).get("backgroundColor")
            fmt_ef = (celda.get("effectiveFormat") or {}).get("backgroundColor")
            celdas.append(fmt_ue or fmt_ef)
        filas.append(celdas)
    return filas


@lru_cache(maxsize=32)
def mapa_de_columnas(pestana: str) -> R.Columnas:
    """Lee las filas 3 y 4 y arma el mapa de columnas de esa pestana.

    Se cachea porque varias herramientas lo llaman por la misma pestana
    en la misma sesion y los encabezados no cambian durante el dia.
    El cache se invalida cuando el proceso reinicia (startup de Hermes).
    """
    filas = leer_valores(
        pestana,
        f"A{R.FILA_ENCABEZADO_GRUPO}:AF{R.FILA_ENCABEZADO_CAMPO}",
    )
    grupo = filas[0] if len(filas) > 0 else []
    campo = filas[1] if len(filas) > 1 else []
    return R.mapear_columnas(grupo, campo)


# --------------------------------------------------------------------------
# Escritura
# --------------------------------------------------------------------------

def escribir_celda(pestana: str, fila: int, columna: int, valor) -> str:
    """Escribe un valor en una celda. Devuelve el rango escrito."""
    _comprobar_permitida(pestana)
    R.validar_fila(fila)
    destino = f"{R.letra_columna(columna)}{fila}"
    try:
        _servicio().spreadsheets().values().update(
            spreadsheetId=_id_hoja(),
            range=f"{_cita(pestana)}!{destino}",
            valueInputOption="USER_ENTERED",
            body={"values": [[valor]]},
        ).execute()
    except Exception as e:
        raise ErrorDeHoja(f"No pude escribir en {pestana}!{destino}: {e}") from e
    return destino


def escribir_fila(pestana: str, fila: int, valores: dict[int, object]) -> list[str]:
    """Escribe varias celdas de una misma fila en una sola llamada.

    `valores` mapea indice de columna -> valor. Se usa batchUpdate de
    values para que o entran todas o no entra ninguna.
    Lanza ErrorDeRegla si valores esta vacio o contiene indices invalidos.
    """
    _comprobar_permitida(pestana)
    R.validar_fila(fila)
    if not valores:
        raise R.ErrorDeRegla(
            "escribir_fila recibio un dict vacio. "
            "Pasa al menos una columna con su valor."
        )
    columnas_invalidas = [c for c in valores if not isinstance(c, int) or c < 1]
    if columnas_invalidas:
        raise R.ErrorDeRegla(
            f"Indices de columna invalidos: {columnas_invalidas}. "
            "Deben ser enteros >= 1."
        )

    data = []
    escritas = []
    for columna, valor in sorted(valores.items()):
        destino = f"{R.letra_columna(columna)}{fila}"
        escritas.append(destino)
        data.append({
            "range": f"{_cita(pestana)}!{destino}",
            "values": [[valor]],
        })

    try:
        _servicio().spreadsheets().values().batchUpdate(
            spreadsheetId=_id_hoja(),
            body={"valueInputOption": "USER_ENTERED", "data": data},
        ).execute()
    except Exception as e:
        raise ErrorDeHoja(f"No pude escribir la fila {fila}: {e}") from e
    return escritas


def pintar_celda(pestana: str, fila: int, columna: int, color_hex: str) -> None:
    """Pinta el fondo de una celda. Asi se marca el avance de un pedido."""
    _comprobar_permitida(pestana)
    R.validar_fila(fila)
    peticion = {
        "repeatCell": {
            "range": {
                "sheetId": _gid(pestana),
                "startRowIndex": fila - 1,      # la API es 0-indexada
                "endRowIndex": fila,
                "startColumnIndex": columna - 1,
                "endColumnIndex": columna,
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": R.hex_a_rgb(color_hex),
                },
            },
            "fields": "userEnteredFormat.backgroundColor",
        }
    }
    try:
        _servicio().spreadsheets().batchUpdate(
            spreadsheetId=_id_hoja(),
            body={"requests": [peticion]},
        ).execute()
    except Exception as e:
        raise ErrorDeHoja(f"No pude pintar la celda: {e}") from e


_RANGO_APENDICE = re.compile(r"!\$?[A-Z]+\$?(\d+)")


def apendizar(pestana: str, rango: str, valores: list) -> int:
    """Agrega una fila al final y devuelve el numero de fila asignado.

    Se usa append en vez de 'leer la ultima fila y sumar uno' porque
    Google serializa los append: dos personas registrando al mismo tiempo
    reciben filas distintas. Ese es el mecanismo que evita folios
    duplicados.
    """
    _comprobar_permitida(pestana)
    try:
        resp = _servicio().spreadsheets().values().append(
            spreadsheetId=_id_hoja(),
            range=f"{_cita(pestana)}!{rango}",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [valores]},
        ).execute()
    except Exception as e:
        raise ErrorDeHoja(f"No pude agregar la fila en {pestana}: {e}") from e

    actualizado = resp.get("updates", {}).get("updatedRange", "")
    coincidencia = _RANGO_APENDICE.search(actualizado)
    if not coincidencia:
        raise ErrorDeHoja(
            f"Google no devolvio la fila asignada ({actualizado!r}). "
            "Revisa la hoja antes de volver a intentar, para no duplicar."
        )
    return int(coincidencia.group(1))


# --------------------------------------------------------------------------
# Utilidades de alto nivel
# --------------------------------------------------------------------------

def pestana_del_mes(fecha: dt.date | None = None) -> str:
    fecha = fecha or dt.date.today()
    return R.elegir_pestana_mes(listar_pestanas(), fecha)


def filas_ocupadas(pestana: str, columna_cliente: int) -> int:
    """Cuantas ventas tiene ya el mes."""
    letra = R.letra_columna(columna_cliente)
    valores = leer_valores(
        pestana, f"{letra}{R.FILA_PRIMER_DATO}:{letra}{R.FILA_ULTIMO_DATO}")
    return sum(
        1 for f in valores
        if f and str(f[0]).strip() and not str(f[0]).startswith("=")
    )


def primera_fila_libre(pestana: str, columna_cliente: int) -> int:
    """La primera fila sin cliente dentro del rango que suman los totales.

    Se busca por la columna CLIENTE y no por 'la ultima fila con algo',
    porque las columnas de formula estan prellenadas hasta la 44 y harian
    ver el mes como lleno.
    """
    letra = R.letra_columna(columna_cliente)
    valores = leer_valores(
        pestana, f"{letra}{R.FILA_PRIMER_DATO}:{letra}{R.FILA_ULTIMO_DATO}")

    for i in range(R.FILAS_DISPONIBLES):
        celda = valores[i][0] if i < len(valores) and valores[i] else ""
        if not str(celda).strip():
            return R.FILA_PRIMER_DATO + i

    raise R.ErrorDeRegla(
        f"El mes '{pestana}' llego a su limite de {R.FILAS_DISPONIBLES} "
        "ventas. Hay que ampliar las formulas de los totales antes de "
        "registrar mas."
    )
