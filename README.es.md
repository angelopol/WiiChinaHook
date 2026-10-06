# WiiChinaHook

Aplicación experimental para Windows que conecta hasta cuatro Wiimotes (incluidos
clones con MotionPlus integrado) y publica controles/movimiento por DSU y datos Wii
completos por WebSocket. No requiere ejecutar Dolphin. Dos modos de conexión:

| Modo | Hardware | Uso |
|---|---|---|
| `dolphinbar` (por defecto) | Mayflash DolphinBar en **modo 4** | El Bluetooth del PC sigue libre para Windows |
| `bluetooth` | Adaptador USB con **libusbK** (Intel `8087:0A2A`) | Passthrough propio con Bumble; el adaptador queda reservado |

## Instalación

Probado con Python 3.13 x64. Se requiere Python 3.11 o posterior.

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock.txt
.venv\Scripts\python -m pip install -e . --no-deps
```

Cierra Dolphin antes de usar el hook: solo un programa debe controlar la DolphinBar
o el adaptador. Para volver a Dolphin, cierra el hook.

## Uso con la DolphinBar (modo por defecto)

1. Pon la DolphinBar en **modo 4** (botón de modo hasta encender el LED 4). En ese
   modo Windows ve cuatro dispositivos HID `057E:0306`, uno por ranura.
2. Empareja cada mando en la barra: SYNC en la barra y después SYNC en el mando.
3. Arranca el hook y consulta el estado:

```powershell
.venv\Scripts\python wiichinahook.py hook
.venv\Scripts\python wiichinahook.py devices
.venv\Scripts\python wiichinahook.py calibrate --slot 0
```

La ranura de la barra (0–3) es el slot de la app; un mando conectado se detecta en
unos dos segundos y su desaparición en unos diez. `pair` no se usa en este modo.
`calibrate` mide el sesgo del giroscopio (mando inmóvil) y lo guarda por ranura en
`.wiichinahook/dolphinbar.json`; `forget --slot N` borra esos ajustes, no el
emparejamiento de la barra.

La barra descarta las respuestas de lectura de memoria de los clones, así que la app
inicializa sin leer: detecta el Nunchuk por el reporte de estado y el MotionPlus por
el formato de sus datos. La calibración del acelerómetro usa valores típicos
(cero `0x80`, 1 g `0x9a`, los de fábrica del clon validado) y la del MotionPlus es
nominal más el sesgo de `calibrate`. La barra no revela la dirección Bluetooth del
mando: DSU publica una MAC local fija por ranura (`02:00:44:42:00:0N`).

## Uso con Bluetooth passthrough (`--mode bluetooth`)

El adaptador de referencia es Intel `8087:0A2A` con **libusbK 3.1.0.0**; mientras
tenga ese controlador, Windows no puede usarlo como Bluetooth normal.

En una terminal:

```powershell
.venv\Scripts\python wiichinahook.py hook --mode bluetooth
```

O fija `"mode": "bluetooth"` en `config.local.json`. En otra terminal, abre una
ventana de sincronización y pulsa el botón rojo **SYNC**:

```powershell
.venv\Scripts\python wiichinahook.py pair --seconds 30
.venv\Scripts\python wiichinahook.py devices
.venv\Scripts\python wiichinahook.py monitor
```

Para conectar mediante **1 + 2**, usa `pair --mode temporary`. En este modo el PIN
usa la dirección del mando; SYNC usa la dirección del host. Si conoces la MAC,
`pair --address XX:XX:XX:XX:XX:XX` evita depender del descubrimiento.
La búsqueda automática considera nombre/clase de dispositivo: revisa `devices`
y usa dirección explícita si hay otros periféricos Bluetooth cerca.

Repite la sincronización para los demás mandos. Se guardan slots `0–3`, claves de
enlace por adaptador y calibración manual. Los mandos conocidos se reconectan
al encenderlos; el mando debe conservar el vínculo (SYNC, no modo temporal).

```powershell
.venv\Scripts\python wiichinahook.py led --slot 0 --mask 0x10
.venv\Scripts\python wiichinahook.py rumble --slot 0 --duration-ms 500
.venv\Scripts\python wiichinahook.py calibrate --slot 0
.venv\Scripts\python wiichinahook.py forget --slot 0
```

`calibrate` mide el sesgo del giroscopio durante tres segundos: mantén el mando
inmóvil. La escala del acelerómetro se obtiene de fábrica; cuando no está
disponible, la API identifica el uso de valores nominales. Nunchuk sin calibración
válida conserva aceleración cruda y un stick con escala nominal.

La vibración dura como máximo cinco segundos y se apaga al cerrar la sesión.
`forget` borra el registro y la clave local; no modifica vínculos guardados dentro
del Wiimote. Espera a que finalicen intentos de conexión/sincronización para usarlo.

## Configuración

`hook` utiliza `config.local.json` si existe; en caso contrario usa la DolphinBar.
Copia `config.example.json` para personalizarlo. `mode` elige `dolphinbar` o
`bluetooth`, y `--mode` en la línea de órdenes lo sustituye. El resto de esta
sección (mandos precargados, `dongle`) solo afecta al modo `bluetooth`.

Puedes precargar mandos:

```json
"wiimotes": [
  {"address": "00:11:22:33:44:55", "slot": 0, "pin_mode": "sync"},
  {"address": "00:11:22:33:44:66", "slot": 1, "pin_mode": "sync"}
]
```

Los slots guardados no se reasignan silenciosamente. Elimina un mando con `forget`
antes de cambiar su slot; retíralo también de la configuración si no deseas que
se agregue de nuevo. Se acepta la configuración antigua con un objeto `wiimote`.
`report_mode` antiguo deja de controlar la salida: ahora se elige según sensores.
En modo `bluetooth`, la MAC publicada por DSU es la real del mando.

`dongle.transport` permite un selector explícito de Bumble, por ejemplo
`usb:8087:0a2a#0`. Un `usb:0` antiguo acompañado de VID/PID se migra a selección
por VID/PID. `ir: false` y `motionplus: false` permiten aislar problemas.

## Salidas

**DSU:** UDP `127.0.0.1:26760`, protocolo 1001, cuatro slots. Configura esta fuente
en Dolphin/Cemu u otro cliente DSU. No actives simultáneamente el passthrough de
Dolphin sobre este mismo adaptador. DSU no equivale a un Wiimote Bluetooth real:
cada emulador debe mapear las entradas que admite.

- Mantiene el mapeo de botones anterior.
- Nunchuk: stick izquierdo, C → L1 y Z → L2.
- Aceleración en g; giroscopio en grados/segundo.
- Sin sensor válido, los campos numéricos DSU quedan en cero; la API conserva la
  diferencia entre ausencia y cero medido.
- IR completo y órdenes de LED/vibración se ofrecen por la API, no por extensiones DSU.

**API:** WebSocket `ws://127.0.0.1:26761`, JSON v1. Solo loopback; no se aceptan
orígenes de navegador. Es una interfaz para clientes locales. Especificación y
ejemplos en [docs/API.md](docs/API.md).

## Diagnóstico y pruebas

```powershell
.venv\Scripts\python wiichinahook.py usb-list
.venv\Scripts\python wiichinahook.py usb-find --vid 0x8087 --pid 0x0a2a
.venv\Scripts\python wiichinahook.py hook --verbose --duration 30
.venv\Scripts\python -m pytest -q
```

Se mantienen `scan-wiimotes`, `usb-hci-info`, `usb-hci-scan`, `usb-hci-listen` y
`usb-hci-pair-window`. Ejecútalos con el hook detenido; son diagnósticos independientes.
El hook no mezcla su transporte Bumble con lecturas PyUSB concurrentes.

Las trazas HCI `.btsnoop` y el estado local se guardan en `.wiichinahook/` (ignorado
por Git). Las trazas pueden contener claves de emparejamiento: no las publiques
sin revisar. Compara una sesión con una captura de Dolphin si un clon falla.

La suite utiliza paquetes sintéticos documentados, conexiones simuladas y sockets
locales. No debe confundirse con capturas ni certificación de hardware real.
Consulta [docs/VALIDATION.md](docs/VALIDATION.md) para las comprobaciones físicas.

## Límites de esta versión

Sin interfaz gráfica, altavoz, mando virtual de Windows ni accesorios distintos
del Nunchuk. Se implementa IR básico de cuatro puntos; no imagen de cámara ni
fusión de orientación. Las peculiaridades de clones se añaden al reproducirlas,
no mediante cambios de PIN o secuencias aleatorias.

Referencias de protocolo:
[Bumble](https://google.github.io/bumble/),
[Wiimote](https://wiibrew.org/wiki/Wiimote),
[MotionPlus](https://wiibrew.org/wiki/Wiimote/Extension_Controllers/Wii_Motion_Plus),
[Nunchuk](https://wiibrew.org/wiki/Wiimote/Extension_Controllers/Nunchuck),
[DSU](https://v1993.github.io/cemuhook-protocol/).
