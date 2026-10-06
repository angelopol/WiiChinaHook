# WiiChinaHook

*[English](README.md) · Español*

Aplicación experimental para Windows que conecta hasta cuatro Wiimotes (incluidos
clones con MotionPlus integrado) y publica controles/movimiento por DSU y datos Wii
completos por una API WebSocket local. No requiere ejecutar Dolphin. Dos modos de conexión:

| Modo | Hardware | Uso |
|---|---|---|
| `dolphinbar` (por defecto) | Mayflash DolphinBar en **modo 4** | El Bluetooth del PC sigue libre para Windows |
| `bluetooth` | Adaptador USB Bluetooth con **libusbK** (p. ej. Intel `8087:0A2A`) | Passthrough propio con Bumble; el adaptador queda reservado mientras funciona |

Una app gráfica (Flet) configura ambos modos y muestra cada mando en vivo, incluida
una vista 3D de la orientación del Wiimote.

## Instalación

Probado con Python 3.13 x64. Se requiere Python 3.11 o posterior.

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock.txt
.venv\Scripts\python -m pip install -e . --no-deps
```

`requirements.lock.txt` incluye la GUI. Solo para consola, instala con
`pip install -e .`; añade la GUI después con `pip install -e .[gui]`.

Cierra Dolphin antes de usar WiiChinaHook: solo un programa debe controlar la
DolphinBar o el adaptador. Para volver a Dolphin, detén el servicio.

## App gráfica

```powershell
.venv\Scripts\python wiichinahook.py gui
```

- **Mandos:** una tarjeta por slot con botones, acelerómetro, velocidad de giro del
  MotionPlus, puntero IR, stick del Nunchuk, batería y una vista de **Orientación**:
  un Wiimote 3D que sigue al mando real (MotionPlus + gravedad). La dirección no tiene
  referencia absoluta y deriva poco a poco; **Recentrar** convierte la dirección
  actual en "apuntando a la pantalla" (plano) o "botones hacia ti" (agarre de lado).
  Sin MotionPlus solo se muestra la inclinación. Vibración, LEDs, calibración del
  sesgo del giroscopio, calibración de escala del MotionPlus y olvidar están a un clic;
  en modo Bluetooth aparece un panel de emparejamiento.
- **Ajustes:** modo de conexión, puertos DSU/API, IR y MotionPlus, guardados en
  `config.local.json`. En modo Bluetooth la app lista los adaptadores con controlador
  libusbK/WinUSB; si no hay ninguno, explica cómo instalarlo con Zadig y ofrece
  abrirlo o descargarlo.
- **Registro:** registro del servicio en vivo.
- Interfaz en inglés y español (selector de idioma en la cabecera).

La GUI ejecuta el servicio en su propio proceso y lo detiene al cerrar la ventana. Si
ya hay un servicio en marcha (por ejemplo `hook` desde la consola), se conecta a él.

## Uso con la DolphinBar (modo por defecto)

1. Pon la DolphinBar en **modo 4** (botón de modo hasta encender el LED 4). En ese
   modo Windows ve cuatro dispositivos HID `057E:0306`, uno por ranura.
2. Empareja cada mando en la barra: SYNC en la barra y después SYNC en el mando.
3. Arranca el servicio y consulta el estado:

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
tenga ese controlador, Windows no puede usarlo como Bluetooth normal. Instala el
controlador con [Zadig](https://zadig.akeo.ie/): *Options → List All Devices*, elige
el adaptador, selecciona libusbK y pulsa *Replace Driver*.

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
y usa dirección explícita si hay otros periféricos Bluetooth cerca. Mientras hay una
ventana de emparejamiento abierta se pausan los intentos de reconexión.

Repite la sincronización para los demás mandos. Se guardan slots `0–3`, claves de
enlace por adaptador y calibración manual. Los mandos conocidos se reconectan
al encenderlos (pulsando un botón); el mando debe conservar el vínculo (SYNC, no
modo temporal).

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

### Calibración de escala del MotionPlus

Algunos clones dan velocidades de giro demasiado altas (el clon validado: ~1,85× en
cabeceo) o con un eje invertido. `calibrate --slot N --axis pitch|roll|yaw` (o
**Calibrar escala** en la GUI) mide cada eje contra la gravedad: con el eje en
horizontal, espera quieto la primera vibración corta y, tras la segunda, gira el mando
despacio unos 90° y mantenlo hasta la vibración larga. Cabeceo: levanta la punta desde
plano. Alabeo: rueda el mando plano hasta dejarlo de lado. Giro: de lado (botones hacia
ti), gíralo como un volante. El ángulo exacto no importa. El factor de cada eje
(negativo si estaba invertido) se guarda con el mando/ranura y se aplica a la API, a la
vista de orientación y a DSU.

| Cabeceo | Alabeo | Giro |
|---|---|---|
| ![Cabeceo: levantar la punta](src/wiichinahook/gui/assets/calibration_pitch.gif) | ![Alabeo: rodar hasta dejarlo de lado](src/wiichinahook/gui/assets/calibration_roll.gif) | ![Giro: como un volante](src/wiichinahook/gui/assets/calibration_yaw.gif) |

La línea amarilla es el eje que se calibra; la barra muestra las fases (gris: quieto,
azul: girar, verde: mantener) y los zigzags marcan las vibraciones. Los GIF se generan
con el propio modelo 3D de la app mediante `tools/make_calibration_gifs.py` (requiere el
extra `[dev]`).

La vibración dura como máximo cinco segundos y se apaga al cerrar la sesión.
`forget` borra el registro y la clave local; no modifica vínculos guardados dentro
del Wiimote. Espera a que finalicen intentos de conexión/sincronización para usarlo.

Los adaptadores clon "CSR 4.0" (`0A12:0001`, `bcdDevice 0x8891`) declaran una
configuración USB alternativa duplicada; Windows se niega a iniciarlos con libusbK,
WinUSB o UsbDk (Código 10), que es también la razón por la que fallan con el
passthrough de Dolphin. No están soportados.

## Configuración

`hook` y la GUI utilizan `config.local.json` si existe; en caso contrario usan la
DolphinBar. Copia `config.example.json` para personalizarlo. `mode` elige
`dolphinbar` o `bluetooth`, y `--mode` en la línea de órdenes lo sustituye. El resto
de esta sección (mandos precargados, `dongle`) solo afecta al modo `bluetooth`.

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
- Aceleración en g; giroscopio en grados/segundo, con los ejes y signos que espera el
  cliente DSU de Dolphin (x izquierda, y abajo, z adelante; pitch arriba, yaw y roll a
  la derecha).
- Sin sensor válido, los campos numéricos DSU quedan en cero; la API conserva la
  diferencia entre ausencia y cero medido.
- IR completo, orientación y órdenes de LED/vibración se ofrecen por la API, no por
  extensiones DSU.

**API:** WebSocket `ws://127.0.0.1:26761`, JSON v1. Solo loopback; no se aceptan
orígenes de navegador. Es una interfaz para clientes locales; la GUI también la usa.
Especificación y ejemplos en [docs/API.es.md](docs/API.es.md).

## Diagnóstico y pruebas

```powershell
.venv\Scripts\python wiichinahook.py usb-list
.venv\Scripts\python wiichinahook.py usb-find --vid 0x8087 --pid 0x0a2a
.venv\Scripts\python wiichinahook.py hook --verbose --duration 30
.venv\Scripts\python -m pytest -q
```

Se mantienen `scan-wiimotes`, `usb-hci-info`, `usb-hci-scan`, `usb-hci-listen` y
`usb-hci-pair-window`. Ejecútalos con el servicio detenido; son diagnósticos
independientes. El servicio no mezcla su transporte Bumble con accesos PyUSB concurrentes.

Las trazas HCI `.btsnoop`, `hook.log` y el estado local se guardan en `.wiichinahook/`
(ignorado por Git). Las trazas pueden contener claves de emparejamiento: no las
publiques sin revisar. Compara una sesión con una captura de Dolphin si un clon falla.

La suite utiliza paquetes sintéticos documentados, conexiones simuladas, sockets
locales y algunas capturas del clon real (`tests/data/`). No es una certificación de
hardware. Consulta [docs/VALIDATION.es.md](docs/VALIDATION.es.md) para las
comprobaciones físicas.

## Límites de esta versión

Sin altavoz, mando virtual de Windows ni accesorios distintos del Nunchuk. Solo IR
básico de cuatro puntos (sin imagen de cámara). La dirección de la orientación deriva
(no hay magnetómetro) y la escala nominal del MotionPlus del clon es demasiado alta
(~1,3–1,85×) hasta que se hace la calibración de escala de cada eje. Las peculiaridades
de clones se añaden al reproducirlas, no mediante cambios de PIN o secuencias aleatorias.

Referencias de protocolo:
[Bumble](https://google.github.io/bumble/),
[Wiimote](https://wiibrew.org/wiki/Wiimote),
[MotionPlus](https://wiibrew.org/wiki/Wiimote/Extension_Controllers/Wii_Motion_Plus),
[Nunchuk](https://wiibrew.org/wiki/Wiimote/Extension_Controllers/Nunchuck),
[DSU](https://v1993.github.io/cemuhook-protocol/).
