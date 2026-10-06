# Altavoz del Wiimote

*[English](SPEAKER.md) · Español*

WiiChinaHook puede reproducir sonidos cortos en el altavoz del mando: al conectarse un
mando, al cambiar de modo, con batería baja o a petición. Es **opcional y está
desactivado por defecto**, y aún no se ha comprobado con el mando real (ver
[Límites](#límites)).

## Uso

**GUI.** *Ajustes → Altavoz (opcional)*:

1. Activa *Reproducir sonidos de eventos* y ajusta el volumen.
2. Para cada evento, elige un sonido integrado, *Desactivado* o *Archivo .wav…* (y
   escribe la ruta del archivo). ▶ lo reproduce en el primer mando conectado.
3. *Guardar*. Se aplica al momento si el servicio está en marcha.

Cada tarjeta de mando tiene además un botón **Sonido** que reproduce una campanilla en
ese mando.

**CLI** (con el hook en marcha):

```powershell
wiichinahook sound --slot 0                         # campanilla
wiichinahook sound --slot 1 --sound alert --volume 0.8
wiichinahook sound --slot 0 --sound C:\Sonidos\moneda.wav
```

**API:** `play_sound` `{"slot": 0, "sound": "chime" | "<ruta>.wav", "volume": 0..1}`
responde al terminar el sonido, con `seconds`. `speaker_config` reemplaza los ajustes de
abajo. Ver [API.es.md](API.es.md).

**Configuración** (`config.local.json`):

```json
"speaker": {
  "enabled": true,
  "volume": 0.5,
  "events": {"connect": "chime", "mode": "count", "low_battery": "sonidos/bateria.wav"}
}
```

| Evento | Cuándo |
|---|---|
| `connect` | Un mando queda listo |
| `mode` | Cambia el modo (B + flecha, la GUI o la bandeja). `count` reproduce N blips para el modo N |
| `low_battery` | La batería baja del 15 % (una vez, hasta que vuelva a superar el 25 %) |

- **Sonidos integrados:** `beep`, `blip`, `chime`, `alert`, `count`. `null` desactiva un
  evento.
- **Sonidos propios:** archivos `.wav` PCM de 8 o 16 bits, con cualquier frecuencia y
  número de canales, de 10 s como máximo. Se convierten a 3 kHz mono y se normalizan,
  porque el altavoz suena bajo. Las rutas relativas parten de la carpeta del archivo de
  configuración.
- **Reproducción:** un sonido nuevo corta el que suena en ese mando.

## Cómo funciona

El altavoz se configura como describe [wiibrew](https://wiibrew.org/wiki/Wiimote#Speaker):

1. Se activa (reporte `0x14`) y se silencia (`0x19`).
2. Se escribe `0xA20009 = 01` y `0xA20001 = 08`.
3. Se escribe la configuración en `0xA20001`: formato ADPCM Yamaha de 4 bits, registro
   de frecuencia `0x07D0` (6 MHz / 2000 = 3 kHz) y volumen.
4. Se escribe `0xA20008 = 01` y se quita el silencio.

El audio sale en reportes `0x18`: 20 bytes, es decir 40 muestras, cada 13,3 ms. Para que
cada sonido empiece sin retraso:

- Las escrituras de configuración se envían seguidas, sin esperar confirmaciones, como
  hacen los juegos de Wii. El canal mantiene su orden.
- Tras un sonido, el altavoz solo se silencia. Sigue configurado, así que el siguiente
  sonido con el mismo volumen solo necesita quitar el silencio. El primer reporte de
  audio sale en pocos milisegundos.
- Tras 15 s en silencio se apaga, lo que evita el siseo y ahorra batería.

El codificador usa las mismas tablas que el decodificador del altavoz de Dolphin, y el
orden de los nibbles (el alto primero) es el que lee ese decodificador.

La parte delicada es el ritmo. Si los reportes llegan tarde, el búfer del mando se vacía
y el sonido se entrecorta. Si llegan antes de tiempo, se desborda. El bucle asyncio en
Windows tiene una granularidad de unos 15 ms, así que un hilo dedicado marca el ritmo
con plazos absolutos. Desde Python 3.11, `time.sleep` usa un temporizador de alta
resolución en Windows. Ese hilo entrega cada reporte al bucle de eventos, que es el
dueño del transporte.

## Límites

- **Sin probar en este clon:** muchos clones traen un altavoz débil, decodifican el
  ADPCM de otra forma o no tienen el altavoz funcional.
- **DolphinBar:** sabemos que reenvía las escrituras de registros (`0x16`), pero no si
  reenvía los reportes de audio `0x18` ni con qué latencia. Por Bluetooth passthrough
  (Bumble) controlamos L2CAP directamente y no debería haber problema.
- **Calidad:** la del mando original, tipo teléfono. Sirve para efectos, no para música.
- **Audio en tiempo real:** reenviar el audio del PC al mando no está implementado.
  Añadiría una latencia notable.

Para probarlo: conecta el mando y pulsa **Sonido** en su tarjeta, o ejecuta
`wiichinahook sound --slot 0`. Hazlo primero por Bluetooth passthrough y después por la
DolphinBar. Si el clon suena mal o no suena, no vale la pena seguir.

## Integración con Dolphin (no implementada)

Hoy el altavoz solo funciona con los sonidos propios de WiiChinaHook. En un juego
emulado por Dolphin, el audio del altavoz del mando **no** llega al mando:

- DSU (cemuhook) solo transporta entradas. No tiene ningún mensaje para audio.
- Con un Wii Remote emulado, Dolphin recibe los datos del altavoz que envía el juego
  (reportes `0x18` y registros del altavoz) en su altavoz emulado
  (`Source/Core/Core/HW/WiimoteEmu/Speaker.cpp`). Los decodifica y los mezcla con el
  audio normal del PC. Nunca los envía a nadie más.

Las rutas posibles, de mejor a peor:

### 1. Que Dolphin reenvíe los datos del altavoz a WiiChinaHook (recomendada)

Un pequeño parche de Dolphin (un fork, o un PR propuesto al proyecto con una opción de
"altavoz externo" para los mandos emulados) enviaría, por cada mando emulado, lo que
escribe el juego:

- la configuración del altavoz (formato, frecuencia, volumen, silencio/encendido);
- cada carga de `0x18`, tal cual.

El destino sería un puerto UDP local. WiiChinaHook aplicaría esa misma configuración en
el mando real y reenviaría las cargas con su hilo de ritmo. El audio del juego ya viene
en el formato del propio mando, así que no hay que recodificar nada, y la latencia es un
solo salto local. Casi todo lo necesario en el lado de WiiChinaHook ya existe: la
configuración, el ritmo y los reportes `0x18`. Falta el receptor.

Un posible formato de paquete (propuesta, no implementado):

| Campo | Tamaño | Valor |
|---|---|---|
| magic | 4 | `WCHS` |
| versión | 1 | `1` |
| slot | 1 | 0–3 (el slot DSU de ese mando) |
| tipo | 1 | `0` = configuración, `1` = audio, `2` = apagar |
| datos | ≤ 21 | configuración: formato, registro de frecuencia (2 bytes LE), volumen · audio: longitud + hasta 20 bytes |

A favor: el audio exacto del juego, baja latencia y sin trucos de audio. En contra:
requiere ese cambio en Dolphin, compilado y mantenido, o aceptado por el proyecto.

### 2. Capturar el audio del PC (no viable)

Dolphin mezcla el audio del altavoz con el del juego en una sola salida. Enrutar Dolphin
por un cable de audio virtual mandaría *todo* el audio del juego al mando. Además
añadiría latencia y obligaría a recodificar a 3 kHz. No compensa.

### 3. Que Dolphin controle el mando ("Wii Remote real")

En ese modo Dolphin envía él mismo los datos del altavoz al mando (*Enable Speaker
Data* en los ajustes del Wii Remote de Dolphin). Es la vía oficial y funciona con mandos
originales. Pero entonces WiiChinaHook debe estar cerrado, porque un mando solo puede
estar controlado por un programa, así que se pierden sus funciones (DSU, modos Xbox).
Además, con este clon falló por los motivos de [VALIDATION.es.md](VALIDATION.es.md): la
DolphinBar descarta las respuestas de lectura de memoria del clon, y la pila Bluetooth
de Windows no logró emparejarlo.

### Cemu

Cemu emula la Wii U. Que sepamos, no saca el audio del altavoz del Wii Remote por
ninguna interfaz externa. No es viable.
