"""Pruebas de la capa de reglas. No tocan Google: corren en segundos.

Varios casos salen de datos reales de VENTAS SPACE 2.0, para que las
rarezas de la hoja queden cubiertas.
"""

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import reglas as R  # noqa: E402


# --------------------------------------------------------------------------
# Telefonos: la hoja los tiene en tres formatos distintos
# --------------------------------------------------------------------------

@pytest.mark.parametrize("entrada", [
    "81 5555 0101",     # como aparece en octubre
    "8155550101",
    "+52 81 5555 0101",
    "52 815 555 0101",
    "(81) 5555-0101",
    "521 81 5555 0101",
])
def test_mismo_telefono_en_cualquier_formato(entrada):
    assert R.normalizar_telefono(entrada) == "8155550101"


def test_telefonos_reales_de_la_hoja():
    assert R.normalizar_telefono("826 555 0202") == "8265550202"
    assert R.normalizar_telefono("8265550303") == "8265550303"


def test_telefono_incompleto_no_sirve_para_comparar():
    assert R.normalizar_telefono("5555 0101") == ""
    assert R.normalizar_telefono("") == ""
    assert R.normalizar_telefono(None) == ""


def test_telefono_legible():
    assert R.telefono_legible("8155550101") == "81 5555 0101"
    # Si no se puede normalizar, se respeta lo que escribio la persona.
    assert R.telefono_legible("ext. 204") == "ext. 204"


# --------------------------------------------------------------------------
# Metodos de pago
# --------------------------------------------------------------------------

@pytest.mark.parametrize("entrada,esperado", [
    ("TRANSF", "TRANSF"),
    ("transferencia", "TRANSF"),
    ("TRASNF", "TRANSF"),              # errata que ya esta en la hoja
    ("EF", "EF"),
    ("efectivo", "EF"),
    ("DEPOSITO", "DEPOSITO"),
    ("TARJETA DE DEBITO", "TDD"),
    ("TARJETA DE CREDITO", "TDC"),
    ("TDC 3 MSI", "TDC 3 MSI"),
    ("TDC 9MSI", "TDC 9 MSI"),
])
def test_normalizar_metodo_pago(entrada, esperado):
    assert R.normalizar_metodo_pago(entrada) == esperado


def test_metodo_desconocido_se_rechaza():
    with pytest.raises(R.ErrorDeRegla) as e:
        R.normalizar_metodo_pago("PAYPAL")
    assert "no reconocido" in str(e.value)


# --------------------------------------------------------------------------
# Colores
# --------------------------------------------------------------------------

def test_ida_y_vuelta_de_color():
    for hexa in R.COLOR_ESTADO.values():
        assert R.rgb_a_hex(R.hex_a_rgb(hexa)) == hexa


def test_celda_sin_color_no_esta_marcada():
    assert not R.esta_marcada(None, "pedido")
    assert not R.esta_marcada({}, "pedido")
    assert not R.esta_marcada(R.hex_a_rgb("FFFFFF"), "pedido")


def test_celda_pintada_se_reconoce():
    assert R.esta_marcada(R.hex_a_rgb("8EAADB"), "pedido")
    assert R.esta_marcada(R.hex_a_rgb("F4B083"), "listas")


def test_color_de_otro_estado_no_cuenta():
    # El azul de 'pedido' no debe leerse como 'listas'.
    assert not R.esta_marcada(R.hex_a_rgb("8EAADB"), "listas")


def test_tolera_el_redondeo_de_la_api():
    # La API devuelve floats; un punto de diferencia por canal es normal.
    casi = {"red": 0.5568628, "green": 0.6666667, "blue": 0.85882354}
    assert R.esta_marcada(casi, "pedido")


def test_estado_es_el_mas_avanzado_marcado():
    colores = {
        "pedido": R.hex_a_rgb("8EAADB"),
        "listas": R.hex_a_rgb("F4B083"),
        "instalado": None,
        "terminado": None,
    }
    assert R.estado_desde_colores(colores) == "listas"


def test_sin_colores_no_hay_estado():
    assert R.estado_desde_colores({e: None for e in R.ESTADOS}) is None


# --------------------------------------------------------------------------
# Avance de estados
# --------------------------------------------------------------------------

def test_avance_normal():
    R.validar_avance(None, "pedido")
    R.validar_avance("pedido", "listas")
    R.validar_avance("listas", "instalado")
    R.validar_avance("instalado", "terminado")


def test_no_se_puede_retroceder():
    with pytest.raises(R.ErrorDeRegla) as e:
        R.validar_avance("instalado", "pedido")
    assert "regresar" in str(e.value)


def test_no_se_puede_saltar_un_paso():
    with pytest.raises(R.ErrorDeRegla) as e:
        R.validar_avance("pedido", "terminado")
    assert "listas" in str(e.value) and "instalado" in str(e.value)


def test_marcar_dos_veces_el_mismo_estado_avisa():
    with pytest.raises(R.ErrorDeRegla) as e:
        R.validar_avance("listas", "listas")
    assert "ya estaba" in str(e.value)


def test_estado_inventado_se_rechaza():
    with pytest.raises(R.ErrorDeRegla):
        R.validar_avance("pedido", "entregado")


# --------------------------------------------------------------------------
# Limites de fila
# --------------------------------------------------------------------------

def test_fila_valida():
    R.validar_fila(5)
    R.validar_fila(44)


def test_fila_de_encabezado_se_rechaza():
    with pytest.raises(R.ErrorDeRegla):
        R.validar_fila(4)


def test_fila_fuera_del_rango_de_totales_se_rechaza():
    with pytest.raises(R.ErrorDeRegla) as e:
        R.validar_fila(45)
    assert "44" in str(e.value)


def test_aviso_de_capacidad():
    assert R.aviso_de_capacidad(5) is None
    assert "Quedan" in R.aviso_de_capacidad(31)
    assert "limite" in R.aviso_de_capacidad(40)


# --------------------------------------------------------------------------
# Encabezados: lo mas delicado, porque las hojas no son todas iguales
# --------------------------------------------------------------------------

# Fila 3 y 4 de 'OCTUBRE 2026 ANGELA' (datos desde la columna D).
FILA3_JUN_EN_ADELANTE = [
    "", "", "", "MES", "VENDEDOR", "FECHA", "CLIENTE", "TELEFONO",
    "RAZON SOCIAL", "TOTAL", "ANTICIPO", "", "", "LIQ", "", "",
    "PENDIENTE", "PEDIDO", "LISTAS", "DETALLES", "INSTALADO",
    "TERMINADO", "COMENTARIOS",
]
FILA4_JUN_EN_ADELANTE = [
    "", "", "", "", "", "", "", "", "", "", "$$$", "METODO", "FECHA",
    "$$$", "METODO", "FECHA", "$$$", "FECHA", "FECHA", "DESCRIPCION",
    "FECHA", "FECHA", "DESCRIPCION DE LO VENDIDO",
]

# De enero a mayo todo esta una columna a la izquierda.
FILA3_ENE_A_MAY = FILA3_JUN_EN_ADELANTE[1:]
FILA4_ENE_A_MAY = FILA4_JUN_EN_ADELANTE[1:]


def test_columnas_de_octubre():
    c = R.mapear_columnas(FILA3_JUN_EN_ADELANTE, FILA4_JUN_EN_ADELANTE)
    assert c.grupo("CLIENTE") == 7      # G
    assert c.grupo("TOTAL") == 10       # J
    assert c.grupo("PEDIDO") == 18      # R
    assert R.letra_columna(c.grupo("CLIENTE")) == "G"


def test_columnas_de_enero_estan_corridas():
    c = R.mapear_columnas(FILA3_ENE_A_MAY, FILA4_ENE_A_MAY)
    assert c.grupo("CLIENTE") == 6      # F, una menos que octubre
    assert R.letra_columna(c.grupo("CLIENTE")) == "F"


def test_subcampos_de_anticipo_y_liquidacion():
    c = R.mapear_columnas(FILA3_JUN_EN_ADELANTE, FILA4_JUN_EN_ADELANTE)
    assert c.campo("ANTICIPO", "$$$") == 11     # K
    assert c.campo("ANTICIPO", "METODO") == 12  # L
    assert c.campo("ANTICIPO", "FECHA") == 13   # M
    assert c.campo("LIQ", "$$$") == 14          # N
    assert c.campo("LIQ", "METODO") == 15       # O


def test_encabezado_con_acento_se_encuentra():
    c = R.mapear_columnas(["", "TELEFONO"], ["", ""])
    assert c.grupo("Teléfono") == 2


def test_columna_inexistente_da_mensaje_util():
    c = R.mapear_columnas(FILA3_JUN_EN_ADELANTE, FILA4_JUN_EN_ADELANTE)
    with pytest.raises(R.ErrorDeRegla) as e:
        c.grupo("FOLIO")
    assert "No encontre" in str(e.value)


def test_hoja_sin_encabezados_se_rechaza():
    with pytest.raises(R.ErrorDeRegla):
        R.mapear_columnas([], [])


def test_letra_columna():
    assert R.letra_columna(1) == "A"
    assert R.letra_columna(26) == "Z"
    assert R.letra_columna(27) == "AA"
    assert R.letra_columna(32) == "AF"


# --------------------------------------------------------------------------
# Pestanas de mes
# --------------------------------------------------------------------------

PESTANAS = [
    "DIC 24 y 2025", "ENERO 2026", "FEBRERO 2026", "MARZO 2026",
    "ABRIL 2026", "MAYO 2026", "JUNIO 2026", "JUNIO 2026 ANGELA",
    "JULIO 2026 ANGELA", "OCTUBRE 2026 ANGELA", "FOLIOS COTIZACIONES",
]


def test_encuentra_la_pestana_con_sufijo():
    assert R.elegir_pestana_mes(
        PESTANAS, dt.date(2026, 10, 15)) == "OCTUBRE 2026 ANGELA"


def test_junio_duplicado_pide_decidir_en_vez_de_adivinar():
    with pytest.raises(R.ErrorDeRegla) as e:
        R.elegir_pestana_mes(PESTANAS, dt.date(2026, 6, 10))
    assert "JUNIO 2026" in str(e.value) and "cual usar" in str(e.value)


def test_mes_sin_pestana_avisa():
    with pytest.raises(R.ErrorDeRegla) as e:
        R.elegir_pestana_mes(PESTANAS, dt.date(2026, 11, 3))
    assert "NOVIEMBRE" in str(e.value)


# --------------------------------------------------------------------------
# Mejoras de robustez (patron del repo de referencia)
# --------------------------------------------------------------------------

class TestHexARgbEstricto:
    """hex_a_rgb ahora valida los caracteres, no solo el largo."""

    def test_color_valido_sigue_funcionando(self):
        rgb = R.hex_a_rgb("8EAADB")
        assert abs(rgb["red"] - 142 / 255) < 0.001
        assert abs(rgb["green"] - 170 / 255) < 0.001
        assert abs(rgb["blue"] - 219 / 255) < 0.001

    def test_color_con_hash_se_acepta(self):
        """El hash opcional al inicio es compatible con CSS."""
        rgb = R.hex_a_rgb("#8EAADB")
        assert abs(rgb["red"] - 142 / 255) < 0.001

    def test_largo_incorrecto_falla(self):
        with pytest.raises(R.ErrorDeRegla, match="invalido"):
            R.hex_a_rgb("8EAA")

    def test_caracteres_no_hex_fallan(self):
        with pytest.raises(R.ErrorDeRegla, match="invalido"):
            R.hex_a_rgb("ZZZZZZ")

    def test_cadena_vacia_falla(self):
        with pytest.raises(R.ErrorDeRegla, match="invalido"):
            R.hex_a_rgb("")

    def test_minusculas_se_aceptan(self):
        """La validacion es insensible a mayusculas."""
        rgb_min = R.hex_a_rgb("8eaadb")
        rgb_may = R.hex_a_rgb("8EAADB")
        assert rgb_min == rgb_may


class TestRgbAHexConClamp:
    """rgb_a_hex ya no produce hex invalido con valores fuera de [0,1]."""

    def test_valor_normal(self):
        assert R.rgb_a_hex({"red": 1.0, "green": 0.0, "blue": 0.0}) == "FF0000"

    def test_sin_color_es_blanco(self):
        assert R.rgb_a_hex(None) == "FFFFFF"
        assert R.rgb_a_hex({}) == "FFFFFF"

    def test_valor_por_encima_del_maximo_se_recorta(self):
        """Valor > 1.0 ya no produce caracter fuera de rango."""
        resultado = R.rgb_a_hex({"red": 1.5, "green": 0.0, "blue": 0.0})
        assert resultado == "FF0000"

    def test_valor_negativo_se_recorta_a_cero(self):
        resultado = R.rgb_a_hex({"red": -0.1, "green": 0.0, "blue": 0.0})
        assert resultado == "000000"

    def test_ida_y_vuelta_de_todos_los_estados(self):
        for hexa in R.COLOR_ESTADO.values():
            assert R.rgb_a_hex(R.hex_a_rgb(hexa)) == hexa


class TestEstaMarcadaConValidacion:
    """esta_marcada valida el estado y la tolerancia."""

    def test_estado_invalido_lanza_error_util(self):
        with pytest.raises(R.ErrorDeRegla) as e:
            R.esta_marcada(None, "enviado")
        assert "enviado" in str(e.value)
        assert "validos" in str(e.value)

    def test_tolerancia_negativa_no_se_acepta(self):
        with pytest.raises(R.ErrorDeRegla, match="Tolerancia"):
            R.esta_marcada(None, "pedido", tolerancia=-1)

    def test_tolerancia_cero_exige_coincidencia_exacta(self):
        exacto = R.hex_a_rgb("8EAADB")
        # Diferencia real: rojo es 0.52 en lugar de 0.557 -> dist > 0
        distinto = {"red": 0.52, "green": 0.6666667, "blue": 0.85882354}
        assert R.esta_marcada(exacto, "pedido", tolerancia=0)
        assert not R.esta_marcada(distinto, "pedido", tolerancia=0)


class TestValidarAvanceTipos:
    """validar_avance rechaza tipos incorrectos explicitamente."""

    def test_estado_no_string_da_error_claro(self):
        with pytest.raises(R.ErrorDeRegla, match="texto"):
            R.validar_avance("pedido", 42)

    def test_none_como_nuevo_da_error(self):
        with pytest.raises(R.ErrorDeRegla):
            R.validar_avance("pedido", None)


# --------------------------------------------------------------------------
# elegir_pestana_mes — fallback month-only (#8)
# --------------------------------------------------------------------------

PESTANAS_SIN_ANIO = [
    "ENERO 2026", "FEBRERO 2026", "JUNIO ANGELA", "JULIO ANGELA",
    "STOCK", "INSTALACIONES",
]


def test_pestana_sin_anio_se_encuentra_por_fallback():
    """Si no hay pestana con el anio, acepta una sin anio en el nombre."""
    resultado = R.elegir_pestana_mes(PESTANAS_SIN_ANIO, dt.date(2026, 6, 15))
    assert resultado == "JUNIO ANGELA"


def test_pestana_con_anio_tiene_prioridad_sobre_sin_anio():
    """Si existen ambas versiones, la del anio explicito gana."""
    pestanas = PESTANAS_SIN_ANIO + ["JUNIO 2026"]
    resultado = R.elegir_pestana_mes(pestanas, dt.date(2026, 6, 15))
    assert resultado == "JUNIO 2026"


def test_fallback_sin_anio_tambien_detecta_duplicado():
    """Dos pestanas sin anio para el mismo mes → pide decidir."""
    with pytest.raises(R.ErrorDeRegla, match="cual usar"):
        R.elegir_pestana_mes(
            ["JULIO ANGELA", "JULIO NORTE"], dt.date(2026, 7, 1)
        )
