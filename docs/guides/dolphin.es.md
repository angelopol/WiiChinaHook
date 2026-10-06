# Dolphin con el modo DSU

*[English](dolphin.md) · Español*

Esta guía configura en Dolphin un **Wii Remote emulado** que recibe de WiiChinaHook, por
DSU (el protocolo "cemuhook"), los botones, el Nunchuk, el acelerómetro y el giroscopio
MotionPlus de tu mando real.

## 1. Pon WiiChinaHook en el modo DSU

1. Abre WiiChinaHook y conecta el mando (DolphinBar o Bluetooth passthrough).
2. Cambia al **modo 2 (DSU)**: mantén **B** y pulsa **→** en el mando (vibra dos veces y
   parpadea el LED 2), o pulsa *Modo 2* en la pestaña *Mando Xbox*.

En los demás modos el servidor DSU sigue anunciando los mandos como conectados, pero no
envía entradas. Así un juego nunca recibe el mismo mando dos veces (Xbox y DSU).

El servidor DSU escucha en `127.0.0.1:26760` (se cambia en *Ajustes*).

## 2. Activa el cliente DSU de Dolphin

1. **Mandos** (*Controllers*) → **Fuentes de entrada alternativas**
   (*Alternate Input Sources*).
2. En la pestaña **Cliente DSU**, marca **Activar**.
3. La lista ya trae `DS4Windows` en `127.0.0.1:26760`. Es la dirección por defecto de
   WiiChinaHook, así que puedes dejarla. Si no, pulsa **Añadir…** e introduce
   `127.0.0.1` y `26760` (cualquier descripción, p. ej. `WiiChinaHook`).
4. Cierra la ventana.

Dolphin pide al servidor sus slots cada segundo. Con WiiChinaHook en marcha, los
dispositivos aparecen como `DSUClient/0/<descripción>`, `DSUClient/1/<descripción>`, …
El número es el slot del mando (slot 0 = mando 1, LED 1).

## 3. Configura el Wii Remote emulado

**Mandos** → *Wii Remote 1*: **Wii Remote emulado** → **Configurar**.

En **Dispositivo**, elige `DSUClient/0/<descripción>`. Cada asignación de abajo es el
nombre que Dolphin muestra para esa entrada DSU. Puedes pulsar un campo y luego el botón
en el mando, o hacer clic derecho en el campo, abrir el editor avanzado y elegir la
entrada de la lista. El editor avanzado es la forma fiable para las entradas de
movimiento, porque al mover el mando se activan varios ejes a la vez.

### Botones (pestaña *General y opciones*)

| Wii Remote | Entrada DSU |
|---|---|
| A | `Circle` |
| B | `Triangle` |
| 1 | `Square` |
| 2 | `Cross` |
| − | `Share` |
| + | `Options` |
| HOME | `PS` |
| Cruceta arriba / abajo / izquierda / derecha | `Pad N` / `Pad S` / `Pad W` / `Pad E` |

La cruceta se envía tal como está en el mando (arriba = la flecha hacia la punta). Para
juegos con el mando en horizontal, Dolphin la gira si marcas
*Opciones → Wii Remote en horizontal* (*Sideways Wii Remote*). No intercambies las
asignaciones para eso.

### Extensión: Nunchuk

En **Extensión**, elige **Nunchuk**. Después, en los botones y el stick de la extensión:

| Nunchuk | Entrada DSU |
|---|---|
| C | `L1` |
| Z | `L2` |
| Stick arriba / abajo | `Left Y+` / `Left Y-` |
| Stick izquierda / derecha | `Left X-` / `Left X+` |

### Movimiento (pestaña *Entrada de movimiento* / *Motion Input*)

El giroscopio necesita un mando con MotionPlus (integrado o acoplado). El acelerómetro
funciona en todos.

| Grupo | Entrada | Entrada DSU |
|---|---|---|
| Acelerómetro | Arriba / Abajo | `Accel Up` / `Accel Down` |
| | Izquierda / Derecha | `Accel Left` / `Accel Right` |
| | Adelante / Atrás | `Accel Forward` / `Accel Backward` |
| Giroscopio | Pitch arriba / abajo | `Gyro Pitch Up` / `Gyro Pitch Down` |
| | Roll izquierda / derecha | `Gyro Roll Left` / `Gyro Roll Right` |
| | Yaw izquierda / derecha | `Gyro Yaw Left` / `Gyro Yaw Right` |

**Comprobación:** con el mando quieto boca arriba, el indicador de acelerómetro de
Dolphin muestra la gravedad hacia abajo. Al inclinar o girar el mando, los indicadores
se mueven en el mismo sentido.

**Puntero:** DSU no lleva datos de la cámara IR, así que el cursor sale del giroscopio.
En el grupo *Point* de *Entrada de movimiento*, déjalo activado y asigna **Recenter**
(recentrar) a una entrada que el juego no use. Una buena opción es − y + a la vez: en el
editor avanzado, escribe `` `Share` & `Options` ``. Apunta al centro de la pantalla y
púlsalo cuando el cursor se desvíe. Ajusta *Total Yaw* / *Total Pitch* (cuánto giras
para recorrer la pantalla) a tu gusto.

Si el ratón también mueve el cursor, borra las asignaciones de *Point* de la pestaña
**Simulación de movimiento** (*Motion Simulation*).

**Sacudidas:** con el acelerómetro real asignado, agitar el mando funciona como en una
Wii. Deja vacío el grupo *Shake* de *Simulación de movimiento*, o asígnalo a un botón
para juegos que piden sacudidas muy fuertes.

### Movimiento del Nunchuk

DSU tiene un único sensor de movimiento por slot, y lleva el del mando. El acelerómetro
del Nunchuk no llega a Dolphin por DSU. Para juegos con sacudidas del Nunchuk (p. ej.
ataques giratorios), asigna el **Shake** de la extensión en **Simulación de movimiento
de la extensión** a un botón, como `` `Pad S` `` o `` `L1` & `L2` `` (C + Z).

Guarda el perfil (*Perfil* → nombre → *Guardar*) para cargarlo en otros juegos y mandos.

## 4. Más mandos

Repite el paso 3 para *Wii Remote 2* con `DSUClient/1/<descripción>`, y así
sucesivamente. El índice sigue el slot de WiiChinaHook (el LED que muestra el mando),
no el orden en que enciendes los mandos.

## Problemas frecuentes

| Síntoma | Solución |
|---|---|
| No aparece ningún `DSUClient` | ¿WiiChinaHook está en marcha? ¿El cliente DSU está activado con el puerto correcto? Solo un programa puede usar el puerto 26760 (cierra DS4Windows/BetterJoy o cambia el puerto). |
| El dispositivo aparece pero nada se mueve | WiiChinaHook no está en el modo DSU: cambia con B + → (o desde la GUI). |
| El dispositivo se desconecta una y otra vez | Actualiza WiiChinaHook (corregido en esta versión) y después quita y vuelve a añadir el servidor. |
| El movimiento va al revés o en espejo | Asignaciones intercambiadas. Revisa la tabla de arriba y pon el mando quieto boca arriba. |
| El cursor se desvía | Asigna **Recenter** (arriba). La calibración rápida de WiiChinaHook (pestaña *Mandos*) también renueva el sesgo del giroscopio. |
| El giroscopio no hace nada | Mando sin MotionPlus, o MotionPlus sin activar (la pestaña *Mandos* muestra "MotionPlus"). |

Ver también: [guía de Cemu](cemu.es.md) · [README](../../README.es.md)
