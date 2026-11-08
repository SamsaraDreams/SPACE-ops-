"""Servidor MCP space-ops para SPACE.

Arranca por stdio: Hermes lo lanza como subproceso, sin puertos ni URL
publica. Cada herramienta valida sus entradas y devuelve lo que hizo,
para que el agente pueda confirmarlo al equipo.

Expone herramientas de lectura y la herramienta de escritura marcar_estado,
validada con el conjunto de pruebas antes de conectar a la hoja real.
"""

from __future__ import annotations

import logging
import os
import re
import sys

try:
    # SDK 2.x: FastMCP se renombro a MCPServer.
    from mcp.server.mcpserver import MCPServer as ServidorMCP
except ImportError:  # pragma: no cover - depende de la version instalada
    from mcp.server.fastmcp import FastMCP as ServidorMCP

import reglas as R
import sheets

# El log va a stderr: stdout es el canal del protocolo MCP y cualquier
# linea suelta ahi rompe la comunicacion con Hermes.
logging.basicConfig(
    level=os.environ.get("SPACE_OPS_LOG", "INFO"),
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("space-ops")

mcp = ServidorMCP("space-ops")


def _responder(fn, *args, **kwargs) -> dict:
    """Envuelve cada herramienta para que un fallo llegue como dato.

    El agente necesita poder decirle al equipo que paso. Una excepcion
    sin envolver se convierte en un error de protocolo y el agente se
    queda sin contexto para explicarlo.
    """
    try:
        return {"ok": True, **fn(*args, **kwargs)}
    except R.ErrorDeRegla as e:
        log.warning("regla: %s", e)
        return {"ok": False, "motivo": "regla", "mensaje": str(e)}
    except sheets.ErrorDeHoja as e:
        log.error("hoja: %s", e)
        return {"ok": False, "motivo": "hoja", "mensaje": str(e)}
    except Exception as e:  # noqa: BLE001
        log.exception("inesperado")
        return {
            "ok": False,
            "motivo": "inesperado",
            "mensaje": f"{type(e).__name__}: {e}",
        }



# --------------------------------------------------------------------------
# Auxiliares privados
# --------------------------------------------------------------------------

def _fila_por_folio(pestana: str, columnas: "R.Columnas", folio: str) -> "int | None":
    """Devuelve la fila de datos donde vive el folio, o None si no existe.

    El folio vive dentro del texto de comentarios con formato 'F:175'.
    Se busca con una expresion regular tolerante a espacios y puntos.
    """
    col_comentarios = columnas.grupo("COMENTARIOS")
    letra_com = R.letra_columna(col_comentarios)
    comentarios = sheets.leer_valores(
        pestana,
        f"{letra_com}{R.FILA_PRIMER_DATO}:{letra_com}{R.FILA_ULTIMO_DATO}",
    )
    buscado = str(folio).strip().upper().lstrip("F").lstrip(":").strip()
    for i, celda in enumerate(comentarios):
        texto = str(celda[0]).upper() if celda else ""
        if not texto:
            continue
        for encontrado in re.findall(r"\bF\s*[:.]?\s*(\d{1,4})\b", texto):
            if encontrado == buscado:
                return R.FILA_PRIMER_DATO + i
    return None


def _colores_de_fila(pestana: str, columnas: "R.Columnas", fila: int) -> "dict[str, object]":
    """Lee los colores de todas las celdas de estado en una sola llamada."""
    cols = {est: columnas.grupo(enc) for est, enc in R.COLUMNA_ESTADO.items()}
    c_min, c_max = min(cols.values()), max(cols.values())
    rango = (f"{R.letra_columna(c_min)}{fila}:{R.letra_columna(c_max)}{fila}")
    celdas = sheets.leer_colores(pestana, rango)
    fila_datos = celdas[0] if celdas else []
    return {
        est: (fila_datos[col - c_min] if col - c_min < len(fila_datos) else None)
        for est, col in cols.items()
    }


# --------------------------------------------------------------------------
# leer_estado_pedido
# --------------------------------------------------------------------------

def _leer_estado(folio: str, mes: str | None) -> dict:
    pestana = mes or sheets.pestana_del_mes()
    columnas = sheets.mapa_de_columnas(pestana)

    col_cliente = columnas.grupo("CLIENTE")
    letra_cli = R.letra_columna(col_cliente)
    clientes = sheets.leer_valores(
        pestana, f"{letra_cli}{R.FILA_PRIMER_DATO}:{letra_cli}{R.FILA_ULTIMO_DATO}")

    # El folio vive dentro del texto de comentarios, con formato 'F:175'.
    # Cuando exista la columna de folio propia, esto se simplifica.
    fila_encontrada = _fila_por_folio(pestana, columnas, folio)

    if fila_encontrada is None:
        return {
            "encontrado": False,
            "mensaje": (
                f"No encontre el folio {folio} en '{pestana}'. "
                "Puede estar en otro mes, o la venta no tiene folio anotado."
            ),
        }

    colores = _colores_de_fila(pestana, columnas, fila_encontrada)

    estado = R.estado_desde_colores(colores)
    i = fila_encontrada - R.FILA_PRIMER_DATO
    cliente = ""
    if 0 <= i < len(clientes) and clientes[i]:
        cliente = str(clientes[i][0])

    siguiente = None
    if estado is None:
        siguiente = R.ESTADOS[0]
    elif estado != R.ESTADOS[-1]:
        siguiente = R.ESTADOS[R.ESTADOS.index(estado) + 1]

    return {
        "encontrado": True,
        "folio": folio,
        "pestana": pestana,
        "fila": fila_encontrada,
        "cliente": cliente,
        "estado": estado or "sin marcar",
        "siguiente_estado": siguiente,
    }


@mcp.tool()
def leer_estado_pedido(folio: str, mes: str | None = None) -> dict:
    """Dice en que estado va un pedido, leyendo el color de sus celdas.

    El equipo marca el avance pintando la celda, no escribiendo texto,
    asi que esta es la unica forma de saber como va un pedido.

    Args:
        folio: numero de folio de la cotizacion, por ejemplo 175 o F:175.
        mes: nombre exacto de la pestana. Si se omite, usa el mes actual.
    """
    return _responder(_leer_estado, folio, mes)


# --------------------------------------------------------------------------
# consultar_stock
# --------------------------------------------------------------------------

def _consultar_stock(texto: str | None, solo_completas: bool) -> dict:
    filas = sheets.leer_valores("STOCK", "B3:L1000")
    busqueda = R.normalizar_nombre(texto) if texto else ""

    # Indices dentro de la fila B..L (11 columnas, 0-indexadas desde B).
    # La columna H queda vacia: el bloque de articulos empieza en I.
    # TODO: leer la fila de encabezados de STOCK y resolver por nombre,
    #       igual que las pestanas de mes, cuando el formato se confirme.
    _COL_NUMERO = 0   # B
    _COL_TIPO   = 1   # C
    _COL_TELA   = 2   # D
    _COL_FASCIA = 3   # E
    _COL_ANCHO  = 4   # F
    _COL_ALTO   = 5   # G
    # H (idx 6) queda vacio en la hoja
    _COL_ARTICULO = 7  # I
    _COL_COLOR    = 8  # J
    _COL_PIEZAS   = 9  # K
    _COL_TAMANO   = 10 # L

    persianas, articulos = [], []
    for fila in filas:
        fila = list(fila) + [""] * (11 - len(fila))
        numero  = fila[_COL_NUMERO]
        tipo    = fila[_COL_TIPO]
        tela    = fila[_COL_TELA]
        fascia  = fila[_COL_FASCIA]
        ancho   = fila[_COL_ANCHO]
        alto    = fila[_COL_ALTO]
        articulo = fila[_COL_ARTICULO]
        color    = fila[_COL_COLOR]
        piezas   = fila[_COL_PIEZAS]
        tamano   = fila[_COL_TAMANO]

        if str(tipo).strip() and str(tipo).strip() != "_":
            registro = {
                "numero": numero,
                "tipo": str(tipo).strip(),
                "tela": str(tela).strip(),
                "fascia": str(fascia).strip().upper() == "SI",
                "ancho_m": ancho,
                "alto_m": alto,
            }
            texto_fila = R.normalizar_nombre(f"{tipo} {tela}")
            if not busqueda or busqueda in texto_fila:
                persianas.append(registro)

        if str(articulo).strip() and str(articulo).strip() != "_":
            completa = str(tamano).strip().upper() == "COMPLETO"
            registro = {
                "articulo": str(articulo).strip(),
                "color": str(color).strip(),
                "piezas": piezas,
                "estado": str(tamano).strip(),
            }
            texto_fila = R.normalizar_nombre(f"{articulo} {color}")
            if (not busqueda or busqueda in texto_fila) and \
               (not solo_completas or completa):
                articulos.append(registro)

    return {
        "busqueda": texto or "todo",
        "persianas": persianas[:40],
        "articulos": articulos[:40],
        "total_persianas": len(persianas),
        "total_articulos": len(articulos),
    }


@mcp.tool()
def consultar_stock(texto: str | None = None,
                    solo_completas: bool = False) -> dict:
    """Busca material disponible en la pestana STOCK.

    Sirve para saber si hay que pedir al proveedor o si ya hay existencia.

    Args:
        texto: tela, tipo, articulo o color a buscar. Vacio devuelve todo.
        solo_completas: deja fuera las piezas ya cortadas.
    """
    return _responder(_consultar_stock, texto, solo_completas)


# --------------------------------------------------------------------------
# buscar_cliente
# --------------------------------------------------------------------------

def _buscar_cliente(telefono: str | None, nombre: str | None,
                    meses: int) -> dict:
    if not telefono and not nombre:
        raise R.ErrorDeRegla("Dame un telefono o un nombre para buscar.")

    objetivo_tel = R.normalizar_telefono(telefono) if telefono else ""
    objetivo_nom = R.normalizar_nombre(nombre) if nombre else ""

    if telefono and not objetivo_tel:
        raise R.ErrorDeRegla(
            f"El telefono {telefono!r} no tiene 10 digitos; no puedo usarlo "
            "para identificar al cliente."
        )

    def _mes_orden(nombre: str) -> tuple:
        n = R.sin_acentos(nombre)
        idx_mes = next((i for i, m in enumerate(R.MESES) if m in n), 0)
        m_anio = re.search(r"\b(20\d\d)\b", n)
        return (int(m_anio.group(1)) if m_anio else 0, idx_mes)

    pestanas = sorted(
        [
            p for p in sheets.listar_pestanas()
            if any(m in R.sin_acentos(p) for m in R.MESES)
            and not any(
                R.sin_acentos(p) == R.sin_acentos(pp)
                for pp in sheets.PESTANAS_PROTEGIDAS
            )
        ],
        key=_mes_orden,
    )[-meses:]

    coincidencias = []
    for pestana in pestanas:
        try:
            columnas = sheets.mapa_de_columnas(pestana)
            c_cli = columnas.grupo("CLIENTE")
            c_tel = columnas.grupo("TELEFONO")
            c_tot = columnas.grupo("TOTAL")
        except R.ErrorDeRegla:
            continue  # pestana con otro formato: se omite, no se adivina

        primera = min(c_cli, c_tel, c_tot)
        ultima = max(c_cli, c_tel, c_tot)
        bloque = sheets.leer_valores(
            pestana,
            f"{R.letra_columna(primera)}{R.FILA_PRIMER_DATO}:"
            f"{R.letra_columna(ultima)}{R.FILA_ULTIMO_DATO}",
        )

        for i, fila in enumerate(bloque):
            def celda(col: int) -> str:
                idx = col - primera
                return str(fila[idx]) if idx < len(fila) else ""

            cliente = celda(c_cli).strip()
            if not cliente:
                continue

            tel_fila = R.normalizar_telefono(celda(c_tel))
            nom_fila = R.normalizar_nombre(cliente)

            coincide = False
            if objetivo_tel and tel_fila and tel_fila == objetivo_tel:
                coincide = True
            elif objetivo_nom and objetivo_nom in nom_fila:
                coincide = True

            if coincide:
                coincidencias.append({
                    "cliente": cliente,
                    "telefono": celda(c_tel).strip(),
                    "total": celda(c_tot).strip(),
                    "pestana": pestana,
                    "fila": R.FILA_PRIMER_DATO + i,
                })

    return {
        "existe": bool(coincidencias),
        "coincidencias": coincidencias[:20],
        "total": len(coincidencias),
        "revisadas": pestanas,
        "nota": (
            "Ya existe; no lo des de alta otra vez."
            if coincidencias else
            "No aparece en los meses revisados; es cliente nuevo."
        ),
    }


@mcp.tool()
def buscar_cliente(telefono: str | None = None, nombre: str | None = None,
                   meses: int = 6) -> dict:
    """Busca un cliente por telefono o nombre, para no darlo de alta dos veces.

    El telefono se normaliza antes de comparar, asi que encuentra al mismo
    cliente aunque este escrito '81 5555 0101' u '8155550101'.

    Args:
        telefono: numero en cualquier formato.
        nombre: nombre o parte del nombre.
        meses: cuantas pestanas de mes revisar, de la mas reciente hacia atras.
    """
    return _responder(_buscar_cliente, telefono, nombre, meses)


# --------------------------------------------------------------------------
# diagnostico
# --------------------------------------------------------------------------

def _diagnostico() -> dict:
    pestanas = sheets.listar_pestanas()
    try:
        del_mes = sheets.pestana_del_mes()
    except R.ErrorDeRegla as e:
        del_mes = f"sin resolver: {e}"

    detalle = {}
    if not str(del_mes).startswith("sin resolver"):
        columnas = sheets.mapa_de_columnas(del_mes)
        c_cli = columnas.grupo("CLIENTE")
        ocupadas = sheets.filas_ocupadas(del_mes, c_cli)
        detalle = {
            "columna_cliente": R.letra_columna(c_cli),
            "ventas_registradas": ocupadas,
            "aviso": R.aviso_de_capacidad(ocupadas),
        }

    return {
        "pestanas": len(pestanas),
        "pestana_del_mes": del_mes,
        **detalle,
    }


@mcp.tool()
def diagnostico() -> dict:
    """Comprueba que el servidor alcanza la hoja y entiende su formato.

    Es la primera herramienta que conviene llamar despues de instalar.
    """
    return _responder(_diagnostico)


# --------------------------------------------------------------------------
# marcar_estado
# --------------------------------------------------------------------------

def _marcar_estado(folio: str, estado: str, mes: str | None) -> dict:
    pestana = mes or sheets.pestana_del_mes()
    columnas = sheets.mapa_de_columnas(pestana)

    fila_encontrada = _fila_por_folio(pestana, columnas, folio)

    if fila_encontrada is None:
        return {
            "encontrado": False,
            "mensaje": (
                f"No encontre el folio {folio} en '{pestana}'. "
                "Puede estar en otro mes, o la venta no tiene folio anotado."
            ),
        }

    # Leer el estado actual antes de escribir.
    colores_actuales = _colores_de_fila(pestana, columnas, fila_encontrada)

    estado_actual = R.estado_desde_colores(colores_actuales)

    # Valida que el avance sea legal (lanza ErrorDeRegla si no).
    R.validar_avance(estado_actual, estado)

    # Pintar la celda del nuevo estado.
    col_estado = columnas.grupo(R.COLUMNA_ESTADO[estado])
    sheets.pintar_celda(pestana, fila_encontrada, col_estado, R.COLOR_ESTADO[estado])

    # Invalidar el cache de columnas no es necesario; el color no afecta
    # la estructura. Pero si mapa_de_columnas esta cacheado por pestana,
    # los colores se leen siempre frescos (leer_colores no esta cacheado).

    return {
        "marcado": True,
        "folio": folio,
        "pestana": pestana,
        "fila": fila_encontrada,
        "estado_anterior": estado_actual or "sin marcar",
        "estado_nuevo": estado,
        "celda": f"{R.letra_columna(col_estado)}{fila_encontrada}",
        "color": R.COLOR_ESTADO[estado],
    }


@mcp.tool()
def marcar_estado(folio: str, estado: str, mes: str | None = None) -> dict:
    """Avanza el estado de un pedido pintando la celda correspondiente.

    El equipo registra el progreso con colores, no con texto. Esta
    herramienta pinta la celda del estado nuevo con el color correcto
    y valida que el avance sea legal (no se puede retroceder ni saltar pasos).

    Args:
        folio: numero de folio, por ejemplo 175 o F:175.
        estado: uno de 'pedido', 'listas', 'instalado', 'terminado'.
        mes: nombre exacto de la pestana. Si se omite, usa el mes actual.
    """
    return _responder(_marcar_estado, folio, estado, mes)


if __name__ == "__main__":
    log.info("space-ops arrancando por stdio")
    mcp.run()
