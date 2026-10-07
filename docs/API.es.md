# API local v1

*[English](API.md) · Español*

WebSocket JSON en `ws://127.0.0.1:26761`. Cada petición lleva `v`, `id`, `command`
y opcionalmente `args`. El servidor responde con el mismo `id` y `ok`.

```json
{"v":1,"id":1,"command":"devices"}
{"v":1,"id":2,"command":"pair","args":{"seconds":30,"mode":"sync"}}
{"v":1,"id":3,"command":"subscribe"}
{"v":1,"id":4,"command":"led","args":{"slot":0,"mask":16}}
{"v":1,"id":5,"command":"rumble","args":{"slot":0,"duration_ms":500}}
{"v":1,"id":6,"command":"calibrate","args":{"slot":0}}
{"v":1,"id":7,"command":"forget","args":{"slot":0}}
{"v":1,"id":8,"command":"calibrate_axis","args":{"slot":0,"axis":"pitch"}}
{"v":1,"id":9,"command":"slot_options","args":{"slot":0,"quick_calibration":true,"combo":"down","ir_calibration":true}}
{"v":1,"id":10,"command":"quick_calibrate","args":{"slot":0}}
{"v":1,"id":11,"command":"gamepad"}
{"v":1,"id":12,"command":"gamepad_mode","args":{"mode":1}}
{"v":1,"id":13,"command":"gamepad_config","args":{"config":{"modifier":"wm_b","mode":1,"modes":[{"buttons":{"A":"wm_a"}},{"type":"dsu"},null,null]}}}
```

`gamepad` devuelve el estado de los modos: `mode`, `modifier`, `modes` (nombres de
plantilla o null), `types` (`"xbox"`, `"dsu"` o null por modo), `pads` (slots con mando virtual), `problems` (por slot, asignaciones que
no puede usar), `error` (p. ej. falta ViGEmBus) y la `config` completa. `gamepad_mode`
cambia el modo de todos los mandos y `gamepad_config` reemplaza la configuración (validada;
los controles Xbox no indicados quedan sin asignar). Un modo es `null` (vacío), una
plantilla Xbox (`"type": "xbox"`, por defecto) o `{"type": "dsu", "name": "DSU", "nunchuk_server": true, "ir_server": true, "ir_range": 0.5}`
(los servidores DSU adicionales para el movimiento del Nunchuk y el puntero IR; puertos
`dsu.nunchuk_port`/`dsu.ir_port` en la configuración, 0 = no se abre), o una plantilla PC
(`"type": "pc"`: `mouse` con `source` `gyro`/`ir`/`nc_stick`/`wm_dpad`/null y sus velocidades,
`shake_g`, y `buttons` que asigna entradas como `wm_a` o `nc_up` a acciones como
`"keys:ctrl+9"`, `"mouse:left"`, `"system:mute"`, `"open:notepad"` o
`"toggle:ctrl+c | ctrl+v"`; ver [PC_MODE.es.md](PC_MODE.es.md)). Un modo 3 vacío en una
configuración anterior a `"version": 4` pasa a ser el modo PC. Los
clientes DSU solo reciben entradas mientras hay un modo DSU activo; en los demás modos los
slots siguen conectados con datos neutros (10 paquetes por segundo en vez de uno por reporte). Una configuración sin `"version": 2` con el modo
2 vacío recibe ahí el modo DSU. Fuentes:
`wm_up/down/left/right/a/b/minus/plus/home/1/2`, `nc_c`, `nc_z`,
`wm_shake_x/y/z` y `nc_shake_x/y/z` (sacudida en un eje, en cualquier sentido; los antiguos
`*_shake_left/right/up/down/forward/back` se siguen aceptando), o hasta tres de ellos unidos
con `+` (botones y/o sacudidas); en cada plantilla, `shake_wm` y `shake_nc` dan los umbrales
por eje en g y `gyro_full_dps`/`gyro_full_dps_y` la sensibilidad horizontal/vertical del
giroscopio. El campo `shakes` del estado (`seq` y los últimos eventos por slot con
`device`, `axis` y `g`) sirve para ajustarlos; sticks `nc_stick`,
`gyro_angle` (apuntado, se mantiene; `angle_full_deg`/`angle_full_deg_y` grados para el máximo),
`gyro` (velocidad, vuelve al centro), `ir`; `chord_window_ms` (0–300, 50 por defecto) es lo que espera un miembro de combinación antes de activarse solo; `startup_mode` (1–4, o null = último modo activo) elige el modo con el que arranca el servicio; `gyro_deadzone` (0–0,5) se aplica a las dos fuentes del giroscopio y `deadzone` al stick del Nunchuk y al IR. Tras `subscribe` llega `{"event":"gamepad","data":...}` cada vez que cambian el modo
o sus avisos, y
`{"event":"xbox","data":{"slot":0,"active":true,"buttons":["A"],"lt":0,"rt":1,"lx":0,"ly":0,"rx":0,"ry":0}}`
cada vez que cambia la salida del mando virtual de un slot (`"active": false` si no tiene).

`subscribe` acepta `"args": {"hz": N}` y `stream_rate` (`{"hz": N}`) lo cambia después: como
máximo N eventos `state`/`xbox` por segundo y slot (1–60, por defecto 60), o 0 para
pausarlos mientras los eventos `gamepad` siguen llegando; al reanudar se envía el estado
más reciente. La GUI usa 30, y 0 mientras está oculta en la bandeja.

`play_sound` (`{"slot": 0, "sound": "chime", "volume": 0.5}`) reproduce un sonido
integrado (`beep`, `blip`, `chime`, `alert`, `count`) o la ruta de un `.wav` en el altavoz
de ese mando. Responde al terminar con `slot`, `sound` y `seconds`, y un sonido nuevo corta
el que esté sonando. `speaker_config` (`{"config": {...}}`) reemplaza los sonidos de
eventos (`enabled`, `volume`, `events`); ver [SPEAKER.es.md](SPEAKER.es.md).

`slot_options` (`quick_calibration`, `combo` — `minus+plus`, `down`, `one+two`, `a+b`, `home`,
`minus+home+plus` —, `combo_hold_ms` 200–3000, `combo_window_ms` 0–1000, `ir_calibration`) cambia en vivo las opciones de
calibración rápida y por barra sensora de un
slot (solo los campos indicados; la respuesta los incluye todos) y `quick_calibrate`
ejecuta la misma calibración rápida que la combinación de botones (respuesta
`{"bias_updated": true|false}`).

`calibrate_noise` (`{"slot": 0, "seconds": 10}`, 10–30 s) mide el ruido del giroscopio con el
mando en reposo y fija un filtro por eje (también corrige el sesgo); responde con
`gyro_noise_dps` (el filtro), `noise_dps`, `bias_dps` y `samples`, o falla si el mando se movió.
`{"slot": 0, "reset": true}` lo quita. `calibration.gyro_noise_dps` del estado lo muestra.

`calibrate_axis` (eje `pitch`, `roll` o `yaw`) ejecuta la calibración guiada de escala
del MotionPlus descrita en el README y responde tras unos 7 s con `factor`,
`rotation_deg`, `correlation` y el nuevo `gyro_scale`; falla con un mensaje si el eje
no estaba horizontal, el giro fue demasiado pequeño o el mando se movió al principio.

`pair` acepta también `address` y `mode: "temporary"`. Su respuesta confirma que
se programó la ventana de sincronización, no que un mando ya esté conectado.
`devices` y la respuesta de `subscribe` contienen `adapter`, `mode`
(`dolphinbar` o `bluetooth`), `ready`, `error`, `pairing` y `devices`.

En modo `dolphinbar`, `pair` devuelve error (los mandos se emparejan en la barra),
`forget` borra los ajustes guardados de la ranura y `address` es una MAC local fija
por ranura (`02:00:44:42:00:0N`), porque la barra no expone la del mando.

Slots válidos: 0–3. LED usa máscara 0x10–0xF0 (solo bits altos); duración de
vibración: 0–5000 ms. Cero apaga el motor.

```json
{"v":1,"id":4,"ok":true,"result":{"slot":0}}
{"v":1,"id":4,"ok":false,"error":{"code":"request_failed","message":"Slot is not connected"}}
```

Después de `subscribe` llegan eventos:

```json
{"v":1,"event":"state","data":{"address":"00:11:22:33:44:55","slot":0,"connected":true,"phase":"ready","buttons":8}}
```

El ejemplo está abreviado. El estado completo contiene:

| Campo | Significado |
|---|---|
| `phase`, `error` | disconnected, connecting, authenticating, opening, initializing o ready; último error |
| `capabilities` | buttons, accelerometer, ir, motionplus, nunchuk |
| `buttons` | Máscara Wii de 16 bits; bits de acelerómetro eliminados |
| `battery` | Fracción 0–1 o null |
| `accel_raw`, `accel_g` | Tres ejes Wii X/Y/Z, crudos de 10 bits y en g |
| `gyro_raw`, `gyro_dps` | Yaw, roll, pitch; crudos y grados/segundo |
| `orientation` | Cuaternión `[w,x,y,z]` del mando al mundo; null sin datos (ver abajo) |
| `ir` | Cuatro puntos `{x,y,size}`; punto invisible = null; sensor sin lectura = null |
| `nunchuk` | `stick` normalizado [-1,1], `stick_raw`, `c`, `z`, `accel_raw`, `accel_g` |
| `extension` | null, nunchuk, motionplus o motionplus+nunchuk |
| `timestamp_us` | Tiempo monotónico del último reporte/estado en microsegundos |
| `accel_timestamp_us`, `gyro_timestamp_us`, `ir_timestamp_us`, `nunchuk_timestamp_us` | Tiempo de cada muestra; 0 antes de recibirla |
| `calibration` | Fuentes de calibración, sesgo manual de gyro y `gyro_scale` (factores yaw, roll, pitch), si existen; `recenter_seq` aumenta en cada calibración rápida y `pitch_offset_deg` es el pitch neutro que tomó (`orientation` se da relativa a él); `heading: "ir"` cuando la barra sensora ya corrige la dirección |

**Ejes.** `accel_g` usa el sistema crudo del Wii, que es dextrógiro: +X hacia la
**izquierda** del mando, +Y hacia **atrás** (el extremo de los botones 1/2), +Z saliendo
de la cara de botones. Boca arriba da Z = +1 g; apuntando al techo, Y = −1 g. Las
velocidades de `gyro_dps` son dextrógiras sobre esos mismos ejes: *pitch* + = bajar la
punta, *roll* + = bajar el lado izquierdo, *yaw* + = antihorario visto desde arriba (la
IMU de Dolphin usa este mismo sistema). `orientation` usa el sistema del mando X derecha,
Y punta, Z cara de botones (el crudo girado 180° sobre Z) y lo lleva a un mundo con X a
la derecha, Y hacia la pantalla y Z hacia arriba. Con MotionPlus se
estima con un filtro complementario a la frecuencia completa de reportes; la
dirección (yaw) no tiene referencia absoluta y deriva. Sin MotionPlus solo refleja la
inclinación del acelerómetro (yaw 0).

Los tiempos son monotónicos del proceso, no fechas UTC. Se conservan muestras
entre reportes intercalados y cada sensor mantiene su propio tiempo. Al desconectar
se limpian las mediciones. IR básico produce `size: null`; sus coordenadas son
crudas, no un cursor de pantalla. Los ejes DSU se adaptan en la frontera de salida al
cliente DSU de Dolphin (`DualShockUDPClient.cpp`): aceleración `(X, −Z, −Y)` y giro
`(−pitch, −yaw, −roll)`, es decir x izquierda, y abajo, z adelante, pitch arriba, yaw y
roll a la derecha.

Eventos de telemetría se agrupan hasta 60 Hz por mando. Los clientes lentos reciben
el estado más reciente; no es un canal de captura sin pérdida. Usa `.btsnoop` para
inspeccionar todos los paquetes. Peticiones limitadas a 16 KiB. Para detener una
suscripción, cierra el WebSocket. Los comandos operan sobre el mismo proceso que
posee el adaptador, evitando una segunda apertura USB.
