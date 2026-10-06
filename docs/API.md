# API local v1

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
```

`pair` acepta también `address` y `mode: "temporary"`. Su respuesta confirma que
se programó la ventana de sincronización, no que un mando ya esté conectado.
`devices` y la respuesta de `subscribe` contienen `adapter`, `ready`, `error`,
`pairing` y `devices`. Slots válidos: 0–3. LED usa máscara 0x10–0xF0 (solo bits
altos); duración de vibración: 0–5000 ms. Cero apaga el motor.

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
| `phase`, `error` | disconnected, connecting, authenticating, initializing o ready; último error |
| `capabilities` | buttons, accelerometer, ir, motionplus, nunchuk |
| `buttons` | Máscara Wii de 16 bits; bits de acelerómetro eliminados |
| `battery` | Fracción 0–1 o null |
| `accel_raw`, `accel_g` | Tres ejes Wii X/Y/Z, crudos de 10 bits y en g |
| `gyro_raw`, `gyro_dps` | Yaw, roll, pitch; crudos y grados/segundo |
| `ir` | Cuatro puntos `{x,y,size}`; punto invisible = null; sensor sin lectura = null |
| `nunchuk` | `stick` normalizado [-1,1], `stick_raw`, `c`, `z`, `accel_raw`, `accel_g` |
| `extension` | null, nunchuk, motionplus o motionplus+nunchuk |
| `timestamp_us` | Tiempo monotónico del último reporte/estado en microsegundos |
| `accel_timestamp_us`, `gyro_timestamp_us`, `ir_timestamp_us`, `nunchuk_timestamp_us` | Tiempo de cada muestra; 0 antes de recibirla |
| `calibration` | Fuente de calibración y sesgo manual de gyro, si existe |

Los tiempos son monotónicos del proceso, no fechas UTC. Se conservan muestras
entre reportes intercalados y cada sensor mantiene su propio tiempo. Al desconectar
se limpian las mediciones. IR básico produce `size: null`; sus coordenadas son
crudas, no un cursor de pantalla. Los ejes DSU se adaptan en la frontera de salida:
aceleración `(X,Z,Y)`, giro `(pitch,yaw,roll)`.

Eventos de telemetría se agrupan hasta 60 Hz por mando. Los clientes lentos reciben
el estado más reciente; no es un canal de captura sin pérdida. Usa `.btsnoop` para
inspeccionar todos los paquetes. Peticiones limitadas a 16 KiB. Para detener una
suscripción, cierra el WebSocket. Los comandos operan sobre el mismo proceso que
posee el adaptador, evitando una segunda apertura USB.
