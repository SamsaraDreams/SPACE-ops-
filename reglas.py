"""Reglas de negocio de SPACE.

Logica pura, sin dependencias de Google. Todo lo que aqui se decide
NO lo decide el modelo: colores de estado, orden de avance,
normalizacion de datos y limites de escritura.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# --------------------------------------------------------------------------
# Estados y sus colores
# --------------------------------------------------------------------------
# El equipo marca el avance pintando la celda, no escribiendo texto.
# Estos son los colores exactos que ya usa la hoja VENTAS SPACE 2.0.

ESTADOS = ("pedido", "listas", "instalado", "terminado")

COLOR_ESTADO = {
    "pedido": "8EAADB",      # azul
    "listas": "F4B083",      # naranja
    "instalado": "FFD965",   # amarillo
    "terminado": "FF0000",   # rojo
}

# Encabezado de la columna de cada estado, tal como aparece en la fila 3.
COLUMNA_ESTADO = {
    "pedido": "PEDIDO",
    "listas": "LISTAS",
    "instalado": "INSTALADO",
    "terminado": "TERMINADO",
}

# --------------------------------------------------------------------------
# Limites de la hoja
# --------------------------------------------------------------------------
# Los totales suman K5:K44, asi que solo caben 40 ventas por mes.
# Escribir fuera de ese rango deja los totales sin cuadrar.

FILA_PRIMER_DATO = 5
FILA_ULTIMO_DATO = 44
FILAS_DISPONIBLES = FILA_ULTIMO_DATO - FILA_PRIMER_DATO + 1  # 40
FILA_AVISO = 35  # a partir de aqui conviene avisar al equipo

# Encabezados: la fila 3 trae los grupos, la 4 los subcampos.
FILA_ENCABEZADO_GRUPO = 3
FILA_ENCABEZADO_CAMPO = 4

# --------------------------------------------------------------------------
# Metodos de pago
# --------------------------------------------------------------------------
# La hoja los tiene escritos de muchas formas (TRANSF, TRASNF, TDC 3 MSI...).
# Se normalizan al escribir, pero se reconocen todas las variantes al leer.

METODOS_PAGO = ("EF", "TRANSF", "DEPOSITO", "TDC", "TDD")

_ALIAS_METODO = {
    "EFECTIVO": "EF",
    "TRANSFERENCIA": "TRANSF",
    "TRASNF": "TRANSF",       # errata que ya existe en la hoja
    "TRANSFER": "TRANSF",
    "DEPOSITO": "DEPOSITO",
    "TARJETA": "TDC",
    "TARJETA DE CREDITO": "TDC",
    "CREDITO": "TDC",
    "TARJETA DE DEBITO": "TDD",
    "DEBITO": "TDD",
}

TIPOS_PAGO = ("anticipo", "liquidacion")


class ErrorDeRegla(ValueError):
    """La operacion viola una regla del negocio. El agente debe reportarla."""


# --------------------------------------------------------------------------
# Texto
# --------------------------------------------------------------------------

def sin_acentos(texto: str) -> str:
    """Quita acentos y pasa a mayusculas, para comparar encabezados y nombres."""
    if texto is None:
        return ""
    plano = unicodedata.normalize("NFKD", str(texto))
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    return plano.strip().upper()


def normalizar_metodo_pago(valor: str) -> str:
    """Devuelve el metodo en su forma canonica.

    Acepta las variantes que ya existen en la hoja. Conserva el sufijo de
    meses sin intereses cuando viene ('TDC 3 MSI' -> 'TDC 3 MSI').
    """
    bruto = sin_acentos(valor)
    if not bruto:
        raise ErrorDeRegla("El metodo de pago viene vacio.")

    # Separa un posible sufijo tipo '3 MSI' o '9MSI'.
    msi = re.search(r"(\d+)\s*MSI", bruto)
    base = re.sub(r"\d+\s*MSI", "", bruto).strip()
    base = base.rstrip(".,-").strip()

    canonico = _ALIAS_METODO.get(base, base)
    if canonico not in METODOS_PAGO:
        raise ErrorDeRegla(
            f"Metodo de pago no reconocido: {valor!r}. "
            f"Usa uno de {', '.join(METODOS_PAGO)}."
        )
    return f"{canonico} {msi.group(1)} MSI" if msi else canonico


def normalizar_telefono(valor: str) -> str:
    """Deja solo los 10 digitos nacionales, para poder comparar clientes.

    La hoja los tiene como '81 5555 0101', '8265550303' y '826 555 0202'.
    Devuelve cadena vacia si no hay suficientes digitos.
    """
    if valor is None:
        return ""
    digitos = re.sub(r"\D", "", str(valor))
    if digitos.startswith("52") and len(digitos) == 12:
        digitos = digitos[2:]
    elif digitos.startswith("521") and len(digitos) == 13:
        digitos = digitos[3:]
    elif digitos.startswith("1") and len(digitos) == 11:
        digitos = digitos[1:]
    return digitos if len(digitos) == 10 else ""


def telefono_legible(valor: str) -> str:
    """Formatea para escribir en la hoja: '81 5555 0101'."""
    d = normalizar_telefono(valor)
    if not d:
        return str(valor or "").strip()
    return f"{d[:2]} {d[2:6]} {d[6:]}"


def normalizar_nombre(valor: str) -> str:
    """Nombre comparable: sin acentos, mayusculas, espacios colapsados."""
    return re.sub(r"\s+", " ", sin_acentos(valor)).strip()


# --------------------------------------------------------------------------
# Colores
# --------------------------------------------------------------------------

def hex_a_rgb(hexa: str) -> dict[str, float]:
    """'8EAADB' -> {'red': 0.557, 'green': 0.667, 'blue': 0.859}.

    La API de Sheets usa floats de 0 a 1, no enteros de 0 a 255.
    Lanza ErrorDeRegla si el hex no tiene exactamente 6 caracteres
    hexadecimales validos (patron del repo de referencia).
    """
    h = str(hexa).lstrip("#").strip().upper()
    if len(h) != 6 or not all(c in "0123456789ABCDEF" for c in h):
        raise ErrorDeRegla(
            f"Color invalido: {hexa!r}. Se esperan 6 caracteres hex, "
            "por ejemplo '8EAADB'."
        )
    try:
        return {
            "red": int(h[0:2], 16) / 255.0,
            "green": int(h[2:4], 16) / 255.0,
            "blue": int(h[4:6], 16) / 255.0,
        }
    except ValueError as e:
        raise ErrorDeRegla(f"Color invalido: {hexa!r}") from e


def rgb_a_hex(rgb: dict | None) -> str:
    """Inverso de hex_a_rgb. Un color ausente en la API significa blanco.

    Los valores se recortan a [0, 255] antes de convertir: la API de Sheets
    puede devolver valores como 0.9999999 que se redondean a 255 sin problema,
    pero valores fuera de rango (raro pero posible con ediciones manuales)
    producian caracteres hex invalidos. Patron del repo de referencia.
    """
    if not rgb:
        return "FFFFFF"
    r = max(0, min(255, round(float(rgb.get("red", 0)) * 255)))
    g = max(0, min(255, round(float(rgb.get("green", 0)) * 255)))
    b = max(0, min(255, round(float(rgb.get("blue", 0)) * 255)))
    return f"{r:02X}{g:02X}{b:02X}"


def _distancia(a: str, b: str) -> int:
    ra, ga, ba = int(a[0:2], 16), int(a[2:4], 16), int(a[4:6], 16)
    rb, gb, bb = int(b[0:2], 16), int(b[2:4], 16), int(b[4:6], 16)
    return abs(ra - rb) + abs(ga - gb) + abs(ba - bb)


def esta_marcada(rgb: dict | None, estado: str, tolerancia: int = 24) -> bool:
    """True si la celda esta pintada con el color de ese estado.

    Se usa tolerancia porque la API devuelve floats y el redondeo puede
    mover un punto cada canal.

    La distancia se calcula canal a canal (Manhattan en RGB):
        d = |R1-R2| + |G1-G2| + |B1-B2|
    Con tolerancia=24 acepta una diferencia de ~8 por canal, suficiente
    para absorber el error de punto flotante de la API.
    """
    if estado not in COLOR_ESTADO:
        raise ErrorDeRegla(
            f"Estado desconocido: {estado!r}. "
            f"Los validos son: {', '.join(ESTADOS)}."
        )
    if not isinstance(tolerancia, int) or tolerancia < 0:
        raise ErrorDeRegla(f"Tolerancia invalida: {tolerancia!r}. Debe ser entero >= 0.")
    actual = rgb_a_hex(rgb)
    if actual in ("FFFFFF", "000000"):
        return False
    return _distancia(actual, COLOR_ESTADO[estado]) <= tolerancia


def estado_desde_colores(colores: dict[str, dict | None]) -> str | None:
    """Devuelve el estado mas avanzado que este marcado.

    `colores` mapea nombre de estado -> color de fondo de esa celda.
    Devuelve None si no hay ninguno marcado.
    """
    alcanzado = None
    for estado in ESTADOS:
        if esta_marcada(colores.get(estado), estado):
            alcanzado = estado
    return alcanzado


# --------------------------------------------------------------------------
# Avance de estados
# --------------------------------------------------------------------------

def validar_avance(actual: str | None, nuevo: str) -> None:
    """Deja avanzar solo hacia adelante, y sin saltarse pasos.

    Lanza ErrorDeRegla con un mensaje que el agente puede repetir tal cual.
    Acepta None como actual (pedido sin estado aun) solo cuando nuevo=='pedido'.
    """
    if not isinstance(nuevo, str):
        raise ErrorDeRegla(
            f"El estado debe ser texto, no {type(nuevo).__name__!r}."
        )
    if nuevo not in ESTADOS:
        raise ErrorDeRegla(
            f"Estado desconocido: {nuevo!r}. Los validos son {', '.join(ESTADOS)}."
        )

    i_nuevo = ESTADOS.index(nuevo)
    i_actual = ESTADOS.index(actual) if actual in ESTADOS else -1

    if i_nuevo == i_actual:
        raise ErrorDeRegla(f"El pedido ya estaba en '{nuevo}'. No cambie nada.")
    if i_nuevo < i_actual:
        raise ErrorDeRegla(
            f"No puedo regresar de '{actual}' a '{nuevo}'. "
            "Si el pedido tuvo un problema, registralo en DETALLES "
            "y pide a una persona que corrija el color."
        )
    if i_nuevo > i_actual + 1:
        faltan = ", ".join(ESTADOS[i_actual + 1:i_nuevo])
        raise ErrorDeRegla(
            f"No puedo marcar '{nuevo}' porque falta pasar por {faltan}."
        )


# --------------------------------------------------------------------------
# Filas
# --------------------------------------------------------------------------

def validar_fila(fila: int) -> None:
    if fila < FILA_PRIMER_DATO:
        raise ErrorDeRegla(
            f"La fila {fila} esta en los encabezados. Los datos empiezan en "
            f"la {FILA_PRIMER_DATO}."
        )
    if fila > FILA_ULTIMO_DATO:
        raise ErrorDeRegla(
            f"La fila {fila} queda fuera del rango que suman los totales "
            f"(hasta la {FILA_ULTIMO_DATO}). El mes ya esta lleno: hay que "
            "ampliar las formulas antes de registrar mas ventas."
        )


def aviso_de_capacidad(ocupadas: int) -> str | None:
    """Mensaje para el equipo cuando el mes se acerca a su limite."""
    if ocupadas >= FILAS_DISPONIBLES:
        return (
            f"El mes llego a su limite de {FILAS_DISPONIBLES} ventas. "
            "No puedo registrar mas hasta ampliar las formulas."
        )
    if ocupadas >= FILA_AVISO - FILA_PRIMER_DATO + 1:
        restan = FILAS_DISPONIBLES - ocupadas
        return f"Quedan {restan} filas libres en el mes."
    return None


# --------------------------------------------------------------------------
# Encabezados
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Columnas:
    """Posicion de cada campo, resuelta por el texto del encabezado.

    Las hojas de enero a mayo estan corridas una columna respecto a las de
    junio en adelante, asi que NUNCA se usa una letra fija.
    """

    por_grupo: dict[str, int]
    por_campo: dict[tuple[str, str], int]

    def grupo(self, nombre: str) -> int:
        clave = sin_acentos(nombre)
        if clave not in self.por_grupo:
            raise ErrorDeRegla(
                f"No encontre la columna '{nombre}' en los encabezados. "
                "Revisa que la pestana tenga el formato de siempre."
            )
        return self.por_grupo[clave]

    def campo(self, grupo: str, campo: str) -> int:
        clave = (sin_acentos(grupo), sin_acentos(campo))
        if clave not in self.por_campo:
            raise ErrorDeRegla(
                f"No encontre la columna '{campo}' dentro de '{grupo}'."
            )
        return self.por_campo[clave]


def mapear_columnas(fila_grupo: list, fila_campo: list) -> Columnas:
    """Construye el mapa de columnas a partir de las filas 3 y 4.

    La fila 3 trae grupos (ANTICIPO abarca K:M) y la 4 los subcampos
    ($$$, METODO, FECHA). Un grupo se extiende hasta el siguiente grupo
    con texto.
    """
    por_grupo: dict[str, int] = {}
    por_campo: dict[tuple[str, str], int] = {}

    ancho = max(len(fila_grupo), len(fila_campo))
    grupo_actual = ""

    for i in range(ancho):
        g = sin_acentos(fila_grupo[i]) if i < len(fila_grupo) else ""
        c = sin_acentos(fila_campo[i]) if i < len(fila_campo) else ""

        if g:
            grupo_actual = g
            por_grupo.setdefault(g, i + 1)  # 1-indexado, como en Sheets
        if c and grupo_actual:
            por_campo.setdefault((grupo_actual, c), i + 1)

    if not por_grupo:
        raise ErrorDeRegla(
            "La pestana no tiene encabezados reconocibles en las filas 3 y 4."
        )
    return Columnas(por_grupo=por_grupo, por_campo=por_campo)


def letra_columna(indice: int) -> str:
    """1 -> A, 27 -> AA. Para armar rangos en notacion A1."""
    if indice < 1:
        raise ErrorDeRegla(f"Indice de columna invalido: {indice}")
    letras = ""
    while indice:
        indice, resto = divmod(indice - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


# --------------------------------------------------------------------------
# Pestanas de mes
# --------------------------------------------------------------------------

MESES = (
    "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
    "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
)


def nombre_mes(fecha) -> str:
    return MESES[fecha.month - 1]


def elegir_pestana_mes(pestanas: list[str], fecha) -> str:
    """Encuentra la pestana del mes, tolerando sufijos como ' ANGELA'.

    Busca primero pestanas que contengan tanto el mes como el anio (p. ej.
    'OCTUBRE 2026 ANGELA'). Si no encuentra ninguna, acepta pestanas que
    contengan el mes sin ningun anio en el nombre (p. ej. 'JUNIO ANGELA'),
    para compatibilidad con hojas mas antiguas.

    Si hay varias candidatas lanza error en vez de adivinar: que una
    persona diga cual es la buena.
    """
    mes = nombre_mes(fecha)
    anio = str(fecha.year)

    candidatas = [
        p for p in pestanas
        if mes in sin_acentos(p) and anio in sin_acentos(p)
    ]
    if not candidatas:
        # Fallback: pestanas del mes sin año explícito en el nombre.
        candidatas = [
            p for p in pestanas
            if mes in sin_acentos(p)
            and not re.search(r"\b20\d\d\b", sin_acentos(p))
        ]
    if not candidatas:
        raise ErrorDeRegla(
            f"No existe la pestana de {mes} {anio}. "
            "Hay que crearla antes de registrar ventas."
        )
    if len(candidatas) > 1:
        raise ErrorDeRegla(
            f"Hay {len(candidatas)} pestanas para {mes} {anio}: "
            f"{', '.join(candidatas)}. Indica cual usar."
        )
    return candidatas[0]
