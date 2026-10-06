# Validación

## Comprobado automáticamente

- Reportes de botones, bits bajos de aceleración, IR básico/extendido, estado,
  Nunchuk y MotionPlus intercalados; paquetes truncados.
- Calibración, checksums, reensamblado de memoria y errores de confirmación.
- PIN binario a través del callback real del Host de Bumble.
- Desconexión, fallo de autenticación y apagado automático de vibración.
- Registro persistente de cuatro slots por adaptador.
- DSU con sockets locales, CRC, selección por slot/MAC y expiración.
- WebSocket real: versión, errores, comandos y suscripciones.
- Reintentos con backoff, borrado de clave rechazada y aceptación entrante como
  central.

Salvo los marcados abajo como capturas, los vectores son sintéticos.

## Comprobado en este equipo

Intel `8087:0A2A`, libusbK `3.1.0.0`, Python 3.13 x64:
enumeración USB, apertura mediante Bumble, inicialización Classic, lectura de
dirección del controlador, arranque de DSU/API y cierre normal del transporte.

### Clon `00:17:AB:AE:1A:6D` (2026-10-05)

Wiimote clónico con MotionPlus integrado (`a6 20 00 05`), Nunchuk (`a4 20 00 00`)
y barra sensora.

| Prueba | Resultado |
|---|---|
| Clon con SYNC | OK: PIN binario, ambos canales HID, LED del slot, reportes `0x37` |
| Reconexión | OK: tras reiniciar la app, pulsar A reconecta con la clave guardada |
| Aceleración | OK en reposo: `[-0.04, 0.04, 1.0] g` con calibración de fábrica |
| MotionPlus | OK en modo passthrough con Nunchuk; `calibrate` elimina el sesgo |
| IR | OK: 2 puntos de la barra sensora |
| Nunchuk | OK: stick, C y Z |
| DSU | OK: slot 1 conectado, MAC real, batería, stick del Nunchuk en LX/LY |
| Cierre | OK: `--duration` termina con `HCI_RESET` y libera el adaptador |

Particularidades del clon, cada una respaldada por una traza y con su prueba
basada en los bytes capturados:

- L2CAP: el *Configure Request* incluye la opción *hint* `80 02 20 03`. Bumble
  respondía `Unknown options` y el canal HID quedaba bloqueado
  (`bumble_compat.py`).
- Una clave de enlace cuyo emparejamiento se interrumpió antes de HID se
  rechaza con `0x05`. La app borra la clave y vuelve al PIN.
- Al reconectar por iniciativa propia, el mando corta (`0x13`) si el host acepta
  como periférico o pide autenticación. La app acepta como central (igual que la
  Wii) y deja que el mando abra HID.
- Las respuestas de memoria `0x21` llegan sin relleno (solo los bytes pedidos),
  y una lectura de 32 bytes llega en un único reporte sobredimensionado.
- Al activar MotionPlus envía estados `0x20` transitorios (`0x28` → `0x2a`). Se
  esperan 0,5 s antes de decidir si hay un cambio real de extensión.
- La calibración de fábrica del MotionPlus y del acelerómetro del Nunchuk no es
  válida. Se usan valores nominales y `calibrate` para el sesgo del giroscopio.

## Matriz física pendiente

| Prueba | Aceptación |
|---|---|
| Sesión de 30 min | Sin bloqueos; muestras continuas y recuperación tras desconexión |
| Aceleración | Cerca de 1 g en el eje vertical, seis orientaciones |
| MotionPlus | Signo correcto de tres giros conocidos |
| IR | Cuatro puntos como máximo; desaparecen al cubrir la cámara |
| Nunchuk | Retirar/insertar con y sin MotionPlus |
| Cuatro mandos | Slots persistentes, sin cruces de datos/LED/vibración |
| USB retirado | Estados desconectados y recuperación al insertar |
| Regreso a Dolphin | Cerrar hook y recuperar el adaptador desde Dolphin |

Para cada prueba registrar modelo del mando/accesorios, configuración, resultado
y ruta de la traza.
