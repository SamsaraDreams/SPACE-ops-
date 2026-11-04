# Notas a futuro — mejoras inspiradas en taylorwilsdon/google_workspace_mcp

Referencia: https://github.com/taylorwilsdon/google_workspace_mcp  
Estado actual de space-ops: stdio, una cuenta, ~1 100 líneas de Python.

Estas notas no son deuda técnica urgente. Son decisiones que vale la pena
tomar en el momento correcto, anotadas antes de olvidar por qué importan.

---

## 1. Scopes OAuth mínimos por servicio

**Cuándo:** Al agregar el primer servicio fuera de Sheets (Gmail para
paquetería, Calendar para citas).

**Qué hacer:** En lugar de un scope amplio para todo, declarar un scope
mínimo por servicio igual que el repo de referencia.

```python
# Hoy (un scope para todo):
ALCANCES = ["https://www.googleapis.com/auth/spreadsheets"]

# Futuro (un scope por servicio, mínimo necesario):
ALCANCES_SHEETS  = ["https://www.googleapis.com/auth/spreadsheets"]
ALCANCES_GMAIL   = ["https://www.googleapis.com/auth/gmail.readonly"]
ALCANCES_CALENDAR = ["https://www.googleapis.com/auth/calendar.events"]
```

**Por qué importa:** Si el token se filtra, el daño queda acotado al
servicio comprometido. Gmail readonly no puede tocar Sheets.

**Referencia en el repo:** `auth/permissions.py` → `SERVICE_PERMISSION_LEVELS`

---

## 2. Permisos de filesystem en el directorio de tokens

**Cuándo:** Antes del primer despliegue en AWS (Fase 1).

**Qué hacer:** Al crear o leer el `token.json`, asegurarse de que el
directorio tenga permisos `0700` y el archivo `0600`. Son dos líneas.

```python
import os, stat

ruta_dir = os.path.dirname(ruta_token)
os.makedirs(ruta_dir, exist_ok=True)
os.chmod(ruta_dir, stat.S_IRWXU)   # 0700: solo el dueño

# Al escribir un token nuevo:
with open(ruta_token, "w") as f:
    json.dump(datos, f)
os.chmod(ruta_token, stat.S_IRUSR | stat.S_IWUSR)  # 0600
```

**Por qué importa:** En un servidor compartido (o si otro proceso se ve
comprometido), un `token.json` con permisos 644 es legible por cualquier
usuario del sistema.

**Referencia en el repo:** `auth/credential_store.py` +
`tests/auth/test_credential_security.py`

---

## 3. Protección SSRF para peticiones HTTP salientes

**Cuándo:** Si Hermes empieza a descargar archivos adjuntos de Gmail,
leer URLs de Drive, o hacer cualquier petición HTTP cuya URL venga de
datos externos.

**Qué hacer:** Antes de hacer un `requests.get(url)` con una URL que
llega del usuario o de la hoja, validar que el hostname no resuelva a
una IP privada. El repo tiene esto en `core/http_utils.py`.

Patrón mínimo para space-ops:

```python
import socket, ipaddress

RANGOS_PRIVADOS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # metadata de AWS
]

def validar_url_externa(url: str) -> None:
    from urllib.parse import urlparse
    host = urlparse(url).hostname
    for ip_str, *_ in socket.getaddrinfo(host, None):
        ip = ipaddress.ip_address(ip_str[-1][0])  # simplificado
        if any(ip in r for r in RANGOS_PRIVADOS):
            raise ValueError(f"URL apunta a red interna: {url!r}")
```

**Por qué importa:** Sin esto, alguien podría pedirle a Hermes que lea
`http://169.254.169.254/latest/meta-data/` y obtener las credenciales
de la instancia EC2.

**Referencia en el repo:** `core/http_utils.py` +
`tests/gdrive/test_ssrf_protections.py`

---

## 4. Rotación automática de tokens

**Cuándo:** Si el `token.json` empieza a expirar seguido o si se agrega
un segundo servicio con su propio ciclo de vida.

**Qué hacer:** El repo de referencia maneja refresh automático en
`auth/google_auth.py`. La librería `google-auth` ya lo hace si se pasa
el `refresh_token`, pero conviene verificar que `credentials.expired`
se compruebe antes de cada llamada larga.

**Referencia en el repo:** `auth/google_auth.py`

---

## 5. Segundo usuario (si SPACE crece)

**Cuándo:** Solo si una tercera persona necesita su propia cuenta de
Google conectada al agente, o si se separan permisos entre admin y
consulta.

**Qué hacer:** El repo de referencia tiene todo el sistema: sesiones
aisladas por usuario, middleware, almacén con key por email. Para
space-ops bastaría un dict `{usuario: ruta_token}` y pasar el usuario
en cada herramienta MCP.

**Por qué no hacerlo ahora:** Hoy son dos personas con la misma cuenta
de Google. Agregar multi-usuario antes de necesitarlo es 500 líneas de
complejidad sin beneficio actual.

**Referencia en el repo:** `auth/mcp_session_middleware.py`,
`auth/oauth21_session_store.py`, `auth/credential_store.py`

---

## 6. Tests de seguridad para rutas de archivo

**Cuándo:** Si se agrega cualquier herramienta que lea o escriba en rutas
que vengan de parámetros externos (nombres de archivo, rutas de adjuntos).

**Qué hacer:** Agregar tests de path traversal similares a los del repo:

```python
# Patrón de test a copiar:
def test_traversal_en_parametro():
    with pytest.raises(ErrorDeRegla):
        alguna_funcion("../../etc/passwd")
```

**Referencia en el repo:** `tests/auth/test_credential_security.py` →
clase `TestPathTraversal`

---

## Resumen de prioridades

| # | Mejora | Trigger |
|---|--------|---------|
| 2 | Permisos 0700/0600 en token | Antes de subir a AWS |
| 1 | Scopes OAuth mínimos | Al agregar Gmail o Calendar |
| 3 | Validación SSRF | Al hacer peticiones HTTP con URLs externas |
| 4 | Rotación automática de tokens | Si hay expiración frecuente |
| 6 | Tests de path traversal | Al manejar rutas de parámetros |
| 5 | Multi-usuario | Solo si llega un tercer acceso |
