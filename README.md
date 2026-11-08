# space-ops

Servidor MCP para el flujo de pedidos de SPACE. Hermes lo arranca como
subproceso por stdio: no hay puertos ni URL pública.

Esta primera versión expone **solo lectura**. Las herramientas de
escritura se agregan cuando estas pasen sus pruebas contra la copia de la
hoja.

## Por qué existe

El skill de Google Workspace de Hermes documenta `sheets get`, `update` y
`append`, pero no el formato de celda. En la hoja de SPACE el avance de
cada pedido se marca **pintando la celda**, no escribiendo texto: de 186
ventas de 2026, la columna PEDIDO tenía texto en 14 casos, LISTAS en 8,
INSTALADO en 2 y TERMINADO en 1. Sin leer y escribir color, un agente no
puede saber cómo va un pedido ni marcar su avance.

## Qué hay dentro

| Archivo | Qué resuelve |
| --- | --- |
| `reglas.py` | Lógica pura: colores, orden de estados, normalización, límites |
| `sheets.py` | Acceso a Sheets, incluido el color de fondo |
| `server.py` | Las herramientas que ve Hermes |
| `tests/` | 62 pruebas que corren sin credenciales |

La separación importa: `reglas.py` no importa nada de Google, así que
toda la lógica delicada se prueba en medio segundo.

## Instalación

```bash
cd ~/space-ops
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env     # y llenar los valores
```

### Credenciales de Google

1. Con la **cuenta dedicada del agente**, crear un proyecto en
   console.cloud.google.com.
2. Activar las APIs de Sheets, Calendar, Gmail y Drive.
3. Crear credenciales OAuth tipo **Desktop app** y descargar el JSON.
4. Correr el flujo de autorización una vez; deja el `token.json` que
   apunta `GOOGLE_TOKEN_PATH`.

El cliente **no entrega contraseñas**: comparte la hoja y el calendario
con el correo de la cuenta del agente, como lo haría con un empleado, y
puede retirar ese acceso cuando quiera.

### Conectarlo a Hermes

En `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  space_ops:
    command: /home/USUARIO/space-ops/.venv/bin/python
    args: [/home/USUARIO/space-ops/server.py]
    env:
      GOOGLE_TOKEN_PATH: /home/USUARIO/space-ops/token.json
      SHEET_ID: EL_ID_DE_LA_COPIA
      CALENDAR_ID: EL_ID_DEL_CALENDARIO
      TZ: America/Mexico_City
    timeout: 60
    tools:
      include: [diagnostico, leer_estado_pedido, consultar_stock, buscar_cliente, marcar_estado]
      prompts: false
      resources: false
```

Las herramientas quedan como `mcp_space_ops_<nombre>`. Lo que no esté en
`tools.include` no se expone, aunque exista en el código.

## Probar

```bash
.venv/bin/python -m pytest tests/ -q      # sin credenciales, medio segundo
```

Ya conectado, la primera llamada debe ser `diagnostico`: confirma que el
servidor alcanza la hoja, resuelve la pestaña del mes y entiende sus
encabezados.

## Las herramientas de esta versión

| Herramienta | Qué hace |
| --- | --- |
| `diagnostico` | Verifica acceso y formato. La primera que hay que llamar |
| `leer_estado_pedido` | En qué estado va un pedido, leyendo el color |
| `consultar_stock` | Material disponible, por tela, tipo o color |
| `buscar_cliente` | Busca por teléfono normalizado o nombre, para no duplicar |
| `marcar_estado` | Avanza el estado de un pedido pintando la celda correspondiente |

## Decisiones que conviene conocer antes de tocar el código

**Las columnas se ubican por el texto del encabezado**, nunca por letra.
Las hojas de enero a mayo están corridas una columna respecto a las de
junio en adelante; una letra fija escribiría en la columna equivocada
durante la mitad del año.

**Los folios se reservan con `append`**, no leyendo la última fila y
sumando uno. Google serializa los append y devuelve la fila asignada, así
que dos personas registrando a la vez reciben folios distintos. Leer y
luego escribir produce duplicados.

**Los estados solo avanzan.** Un intento de retroceder o de saltarse un
paso se rechaza con un mensaje que el agente puede repetirle al equipo.

**Un fallo llega como dato, no como excepción.** Cada herramienta
devuelve `{"ok": false, "motivo": ..., "mensaje": ...}` para que el
agente pueda explicar qué pasó en lugar de quedarse mudo.

**El log va a stderr.** `stdout` es el canal del protocolo MCP: una línea
suelta ahí rompe la comunicación con Hermes.

## Pendiente

- Herramientas de escritura pendientes: `registrar_venta`, `registrar_pago`,
  `agendar_visita`, `registrar_paqueteria`, `folio_cotizacion_siguiente`,
  `registrar_cotizacion`, `pedidos_atrasados`.
- Columna de folio propia en las hojas de mes. Hoy el folio vive dentro
  del texto de comentarios (`F:175`) y solo 2 de 186 ventas lo tienen,
  así que `leer_estado_pedido` encuentra pocos pedidos hasta que exista
  esa columna.
- Pestaña `Log` de solo adición.
- Decidir cuál de las dos pestañas de junio es la buena. Mientras haya
  dos, el servidor pide que una persona lo indique en vez de adivinar.
