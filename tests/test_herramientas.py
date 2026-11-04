"""Prueba las herramientas del servidor contra una hoja simulada.

No necesita credenciales de Google: reemplaza la capa sheets por datos
en memoria copiados de VENTAS SPACE 2.0. Sirve para verificar la logica
de cada herramienta antes de conectar nada real.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import reglas as R  # noqa: E402
import sheets  # noqa: E402
import server  # noqa: E402


# --------------------------------------------------------------------------
# Hoja simulada
# --------------------------------------------------------------------------

PESTANAS = [
    "DIC 24 y 2025", "ENERO 2026", "SEPTIEMBRE 2026 ANGELA",
    "OCTUBRE 2026 ANGELA", "FOLIOS COTIZACIONES", "STOCK", "INSTALACIONES",
]

# Filas 3 y 4 de octubre: los datos empiezan en la columna D.
ENCABEZADOS = [
    ["", "", "", "MES", "VENDEDOR", "FECHA", "CLIENTE", "TELEFONO",
     "RAZON SOCIAL", "TOTAL", "ANTICIPO", "", "", "LIQ", "", "",
     "PENDIENTE", "PEDIDO", "LISTAS", "DETALLES", "INSTALADO",
     "TERMINADO", "COMENTARIOS"],
    ["", "", "", "", "", "", "", "", "", "", "$$$", "METODO", "FECHA",
     "$$$", "METODO", "FECHA", "$$$", "FECHA", "FECHA", "DESCRIPCION",
     "FECHA", "FECHA", "DESCRIPCION DE LO VENDIDO"],
]

# Ventas reales de octubre, con sus comentarios tal cual.
VENTAS = [
    ("ANA LOPEZ", "81 5555 0101", 21083.79, "PERSIANAS (MAN - MOT) F:175"),
    ("SOFIA RUIZ", "826 555 0202", 1600, "PAPEL TAPIZ (2)"),
    ("MARTA DIAZ", "826 555 0404", 4870, "PAPEL TAPIZ (2)"),
    ("LAURA CRUZ", "8265550303", 3600, "PAPEL TAPIZ YS-970626"),
    ("PEDRO GOMEZ", "", 22273.49, "PERSIANA, CORTINA, TAPIZ (F:276)"),
]

STOCK = [
    [1, "ENROLLABLE", "SUNSCREEN NEGRO", "SI", 1.8, 1.2, "",
     "LAMBRIN", "BRASILIA", "15", "COMPLETO"],
    [2, "ENROLLABLE", "BO IPANEMA BLANCO", "SI", 1.3, 1.37, "",
     "LAMBRIN", "GRIS OPORTO", "1", "COMPLETO"],
    [3, "ENROLLABLE", "BO GALAXY GOLDEN DUST", "NO", 0.93, 0.8, "",
     "LAMBRIN", "NOGAL MATE", "15 1/2", "1 CORTADA"],
    [5, "SHEER", "DL RADIANCE GOLD", "_", 1.0, 1.4, "",
     "ANGULO", "CHAMPAGNE", "2 1/2", "1 CORTADA"],
]

# Colores por fila: la venta de ANA (F:175) va en 'listas'.
COLORES = {
    5: {"pedido": "8EAADB", "listas": "F4B083"},
    6: {"pedido": "8EAADB"},
}


def _indice_columna(letras: str) -> int:
    total = 0
    for c in letras:
        total = total * 26 + (ord(c) - 64)
    return total


def _partir_rango(rango: str) -> tuple[int, int, int, int]:
    """'G5:J44' -> (col_inicio, fila_inicio, col_fin, fila_fin), 1-indexado."""
    inicio, _, fin = rango.partition(":")
    fin = fin or inicio

    def partes(ref):
        letras = "".join(c for c in ref if c.isalpha())
        numeros = "".join(c for c in ref if c.isdigit())
        return _indice_columna(letras), int(numeros)

    c1, f1 = partes(inicio)
    c2, f2 = partes(fin)
    return c1, f1, c2, f2


class HojaFalsa:
    """Responde como sheets.py pero desde memoria.

    Construye una cuadricula real y la rebana como lo hace la API, para
    que una prueba que pasa aqui tenga sentido contra Google.
    """

    def __init__(self):
        self.escrituras = []
        self.pintadas = []
        self.cuadricula = self._armar_mes()

    @staticmethod
    def _armar_mes() -> dict[tuple[int, int], object]:
        celdas: dict[tuple[int, int], object] = {}
        for c, valor in enumerate(ENCABEZADOS[0], start=1):
            celdas[(R.FILA_ENCABEZADO_GRUPO, c)] = valor
        for c, valor in enumerate(ENCABEZADOS[1], start=1):
            celdas[(R.FILA_ENCABEZADO_CAMPO, c)] = valor
        for i, (cliente, telefono, total, comentario) in enumerate(VENTAS):
            fila = R.FILA_PRIMER_DATO + i
            celdas[(fila, 7)] = cliente       # G
            celdas[(fila, 8)] = telefono      # H
            celdas[(fila, 10)] = total        # J
            celdas[(fila, 23)] = comentario   # W
        return celdas

    def listar_pestanas(self):
        return list(PESTANAS)

    def leer_valores(self, pestana, rango):
        if pestana == "STOCK":
            return [list(f) for f in STOCK]

        c1, f1, c2, f2 = _partir_rango(rango)
        salida = []
        for fila in range(f1, f2 + 1):
            renglon = [self.cuadricula.get((fila, c), "")
                       for c in range(c1, c2 + 1)]
            # La API recorta las celdas vacias del final de cada fila.
            while renglon and renglon[-1] == "":
                renglon.pop()
            salida.append(renglon)
        while salida and not salida[-1]:
            salida.pop()
        return salida

    def leer_colores(self, pestana, rango):
        c1, f1, c2, f2 = _partir_rango(rango)
        por_encabezado = {v: k for k, v in R.COLUMNA_ESTADO.items()}
        salida = []
        for fila in range(f1, f2 + 1):
            renglon = []
            for c in range(c1, c2 + 1):
                encabezado = (ENCABEZADOS[0][c - 1]
                              if c <= len(ENCABEZADOS[0]) else "")
                estado = por_encabezado.get(encabezado)
                hexa = COLORES.get(fila, {}).get(estado)
                renglon.append(R.hex_a_rgb(hexa) if hexa else None)
            salida.append(renglon)
        return salida

    def mapa_de_columnas(self, pestana):
        return R.mapear_columnas(ENCABEZADOS[0], ENCABEZADOS[1])

    def pestana_del_mes(self, fecha=None):
        return "OCTUBRE 2026 ANGELA"

    def filas_ocupadas(self, pestana, columna_cliente):
        return len(VENTAS)


@pytest.fixture(autouse=True)
def hoja_falsa(monkeypatch):
    falsa = HojaFalsa()
    for nombre in ("listar_pestanas", "leer_valores", "leer_colores",
                   "mapa_de_columnas", "pestana_del_mes", "filas_ocupadas"):
        monkeypatch.setattr(sheets, nombre, getattr(falsa, nombre))
    monkeypatch.setattr(sheets, "PESTANAS_PROTEGIDAS",
                        sheets.PESTANAS_PROTEGIDAS)
    return falsa


# --------------------------------------------------------------------------
# leer_estado_pedido
# --------------------------------------------------------------------------

def test_lee_el_estado_desde_el_color():
    r = server._leer_estado("175", None)
    assert r["encontrado"]
    assert r["cliente"] == "ANA LOPEZ"
    assert r["estado"] == "listas"
    assert r["siguiente_estado"] == "instalado"


def test_encuentra_el_folio_entre_parentesis():
    r = server._leer_estado("276", None)
    assert r["encontrado"]
    assert r["cliente"] == "PEDRO GOMEZ"


def test_acepta_el_folio_con_prefijo_f():
    assert server._leer_estado("F:175", None)["encontrado"]


def test_folio_inexistente_lo_dice_sin_inventar():
    r = server._leer_estado("999", None)
    assert r["encontrado"] is False
    assert "No encontre" in r["mensaje"]


def test_venta_sin_folio_no_se_confunde_con_otra():
    # 'PAPEL TAPIZ (2)' tiene un numero, pero no es un folio.
    r = server._leer_estado("2", None)
    assert r["encontrado"] is False


# --------------------------------------------------------------------------
# consultar_stock
# --------------------------------------------------------------------------

def test_stock_completo():
    r = server._consultar_stock(None, False)
    assert r["total_persianas"] == 4
    assert r["total_articulos"] == 4


def test_stock_filtra_por_tela():
    r = server._consultar_stock("sunscreen", False)
    assert r["total_persianas"] == 1
    assert r["persianas"][0]["fascia"] is True


def test_stock_solo_piezas_completas():
    r = server._consultar_stock(None, True)
    assert all(a["estado"] == "COMPLETO" for a in r["articulos"])
    assert r["total_articulos"] == 2


def test_stock_busca_sin_acentos():
    r = server._consultar_stock("angulo", False)
    assert r["total_articulos"] == 1


# --------------------------------------------------------------------------
# buscar_cliente
# --------------------------------------------------------------------------

def test_encuentra_cliente_por_telefono_en_otro_formato():
    r = server._buscar_cliente("8155550101", None, 2)
    assert r["existe"]
    assert r["coincidencias"][0]["cliente"] == "ANA LOPEZ"


def test_encuentra_cliente_por_nombre_parcial():
    r = server._buscar_cliente(None, "sofia", 2)
    assert r["existe"]


def test_cliente_nuevo_se_reporta_como_nuevo():
    r = server._buscar_cliente("8199999999", None, 2)
    assert r["existe"] is False
    assert "nuevo" in r["nota"]


def test_telefono_incompleto_se_rechaza():
    with pytest.raises(R.ErrorDeRegla) as e:
        server._buscar_cliente("5550101", None, 2)
    assert "10 digitos" in str(e.value)


def test_pide_al_menos_un_criterio():
    with pytest.raises(R.ErrorDeRegla):
        server._buscar_cliente(None, None, 2)


# --------------------------------------------------------------------------
# El envoltorio de errores
# --------------------------------------------------------------------------

def test_un_error_de_regla_llega_como_dato_no_como_excepcion():
    r = server._responder(server._buscar_cliente, None, None, 2)
    assert r["ok"] is False
    assert r["motivo"] == "regla"
    assert "telefono" in r["mensaje"] or "nombre" in r["mensaje"]


def test_una_lectura_buena_marca_ok():
    r = server._responder(server._leer_estado, "175", None)
    assert r["ok"] is True
    assert r["estado"] == "listas"
