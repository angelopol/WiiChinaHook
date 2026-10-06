# Validación

*[English](VALIDATION.md) · Español*

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
  central; búsqueda reintentada mientras otro mando está siendo llamado.
- Transporte DolphinBar simulado con el comportamiento capturado (lecturas perdidas,
  relleno `0x30`, formatos MotionPlus/Nunchuk).
- Filtro de orientación: convenciones de signo, corrección por gravedad y
  reproducción de una captura real del clon (`tests/data/clone_axes_capture.json`).
- GUI sin ventana: modelo, traducciones, ciclo de vida del servicio, conexión a un
  servicio ya en marcha, tarjetas de slot y proyección 3D; detección de adaptadores.

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

### DolphinBar, modo 4, mismo clon (2026-10-06)

Mayflash DolphinBar (`0079:1802` en modo 1; en modo 4, cuatro HID `057E:0306`).

| Prueba | Resultado |
|---|---|
| Datos, confirmaciones `0x22`, estado `0x20` | Llegan; ~235 reportes/s en modo `0x37` |
| Lecturas de memoria `0x21` | **Ninguna llega**: la barra descarta las respuestas sin relleno del clon |
| MotionPlus sin lecturas | OK con `a600f0=55` y `a600fe=04/05/07`, por `WriteFile` y `HidD_SetOutputReport`. En reposo da el mismo sesgo que por Bluetooth directo (5,6 / −4,7 / 11,2 °/s); giros de hasta ±900 °/s |
| Nunchuk | OK: stick con recorrido completo, C, Z; en passthrough con MotionPlus |
| Quitar/poner Nunchuk | Se refleja en el bit "extensión" de los paquetes MotionPlus; **no** llega reporte `0x20` |
| IR | OK, 2 puntos (la barra es la fuente IR) |
| Acelerómetro | 1,0 g en reposo con la calibración típica (la de fábrica del clon) |
| App completa (`hook`) | Ranura detectada en < 0,1 s, lista en ~4 s, `calibrate` guardado, DSU con MAC local, cierre inmediato |
| Salir y volver | Mando apagado: ranura desconectada; al encenderlo, lista de nuevo en ~1 s |
| Mando fuera de la barra | La ranura vacía sigue emitiendo `0x30` de relleno; la vigilancia usa los reportes del modo configurado |

El formato de escritura `0x16` es `[espacio|0x02][dirección 3 bytes][tamaño][16 datos]`.
Las primeras pruebas manuales duplicaron el byte de espacio y concluyeron, por error,
que el MotionPlus no se activaba por la barra.

### Ejes del MotionPlus (captura guiada, 2026-10-06)

Clon por la DolphinBar, mando en reposo y después alabeo, cabeceo y un giro completo
antihorario sobre la mesa.

| Movimiento | Resultado |
|---|---|
| Cabeceo (levantar la punta) | Acelerómetro Y → +0,81; correlación +0,99 entre el ángulo de gravedad y el *pitch* integrado |
| Alabeo | Correlación −0,65 con el ángulo de gravedad X/Z crudo: coherente con *roll* + = bajar el lado izquierdo |
| Giro antihorario | *yaw* integrado +469°, roll/pitch ≈ 0 |

Esta captura por sí sola se interpretó mal: su primera excursión de cabeceo se tomó por
"levantar la punta". Una prueba guiada posterior con posturas mantenidas (punta al techo:
Y = −1 g; lado derecho abajo: X = +1 g), la foto del usuario de lado (X = −1 g con la
punta a la izquierda y los botones hacia el jugador) y la calibración de escala por
gravedad (los tres factores positivos en este sistema) lo resuelven: el sistema crudo es
dextrógiro con +X = izquierda, +Y = atrás (extremo de los botones 1/2), +Z = cara de
botones, y *pitch*/*roll*/*yaw* del MotionPlus son dextrógiros sobre esos ejes (*pitch* + =
bajar la punta, *roll* + = bajar el lado izquierdo, *yaw* + = antihorario). Es también el
sistema de la IMU de Dolphin (`IMUAccelerometer.cpp`, `IMUGyroscope.cpp`). La escala nominal del clon es demasiado alta: el *pitch*
integrado es 1,85× el ángulo de gravedad y el giro completo dio 469° en vez de 360°.
Con la escala 1/1,85 el filtro sigue el cabeceo con un error mediano de 2,6°.

### GUI (2026-10-06)

Probada por el usuario en ambos modos: conexión, botones, acelerómetro, MotionPlus,
LEDs y vibración. Cierre con la X: servicio detenido y sin procesos huérfanos.

### Adaptador clon "CSR 4.0" `0A12:0001` (2026-10-06)

`bcdDevice 0x8891`. Su descriptor declara dos veces la configuración alternativa 5
de la interfaz 1. Windows no lo inicia con libusbK ni WinUSB (Código 10,
`STATUS_INVALID_DEVICE_REQUEST`) y UsbDk 1.0.22 lo enumera pero no puede redirigirlo.
No soportado.

### Ejes DSU (2026-10-06)

Deducidos del código de Dolphin (`DualShockUDPClient.cpp` e `IMUAccelerometer.cpp`):
"Accel Up" = −y, "Accel Left" = +x, "Accel Forward" = +z, y en reposo Dolphin espera
+1 g hacia arriba; "Gyro Pitch Up" = +pitch, "Roll Right" = +roll, "Yaw Right" = +yaw.
Sus grupos IMU los combinan como x = Left − Right, y = Backward − Forward, z = Up − Down
y x = PitchDown − PitchUp, y = RollLeft − RollRight, z = YawLeft − YawRight: el sistema
del Wii. Por eso DSU envía `(X, −Z, −Y)` y `(−pitch, −yaw, −roll)`. Falta confirmarlo en
el propio Dolphin (ver abajo).

### Conexión DSU intermitente en Dolphin (2026-10-06)

Reportado: el dispositivo DSU de Dolphin se conectaba y desconectaba constantemente.
Dolphin pide el estado de los puertos cada segundo y elimina los dispositivos de un
servidor si pasa 1 s sin respuesta; además los recrea cuando cambia el modelo de un slot.
En Windows, los datos enviados a un cliente que había cerrado su socket (Dolphin al
reconfigurar) volvían como WSAECONNRESET en cada `recvfrom`, y el servidor dejaba de leer
ante ese error, así que las peticiones de puertos quedaban sin respuesta (reproducido: 4
de 11 respondidas). Corregido desactivando `SIO_UDP_CONNRESET`, siguiendo la lectura tras
esos errores (11 de 11) y anunciando un modelo constante "giroscopio completo" para los
mandos conectados. Prueba de regresión en `tests/test_dsu.py`; falta confirmarlo en el
propio Dolphin.

### Calibración de escala del MotionPlus

Ajuste contra la gravedad probado con giros simulados sobre cada eje (escala 1,85,
signos invertidos, sesgo) y con la captura real de cabeceo del clon (factor ≈ 1/1,85).

## Matriz física pendiente

| Prueba | Aceptación |
|---|---|
| Sesión de 30 min | Sin bloqueos; muestras continuas y recuperación tras desconexión |
| Aceleración | Cerca de 1 g en el eje vertical, seis orientaciones |
| Escala del MotionPlus | Tras `calibrate --axis` en los tres ejes, un giro de 90° se mide ≈ 90° |
| DSU en Dolphin | Wiimote emulado con movimiento por DSU: en reposo la gravedad apunta hacia abajo en los indicadores de Dolphin; al inclinar o girar se mueven en el mismo sentido |
| Orientación en la GUI | El modelo 3D sigue al mando en los tres ejes; deriva lenta de la dirección |
| IR | Cuatro puntos como máximo; desaparecen al cubrir la cámara |
| Nunchuk | Retirar/insertar con y sin MotionPlus |
| Varios mandos | Slots persistentes, sin cruces de datos/LED/vibración (en ambos modos) |
| USB retirado | Estados desconectados y recuperación al insertar |
| Regreso a Dolphin | Cerrar hook y recuperar el adaptador desde Dolphin |
| Cambio de controlador | Ajustes → Controlador del adaptador: Intel a libusbK y de vuelta al Bluetooth de Windows, con UAC y sin Zadig |
| Calibración rápida | Mantener la combinación ~0,6 s: doble vibración si está quieto (sesgo renovado y recentrado), larga si se mueve |
| Calibración con la barra | Apuntar a la barra elimina la deriva del giro; **verificar el signo de la imagen IR** (al girar a la izquierda la barra debe seguir "de frente") |
| Modos Xbox | B + flechas cambia de modo con N vibraciones; la plantilla de juego maneja un mando Xbox virtual (panel "Dispositivos de juego" de Windows o un juego); la vibración de los juegos llega al Wiimote |
| Sacudidas / stick IR | El sentido de las sacudidas del Wiimote y del Nunchuk y el vertical del stick derecho por IR coinciden con el movimiento |

Para cada prueba registrar modelo del mando/accesorios, configuración, resultado
y ruta de la traza.
