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
3. Añade los servidores de WiiChinaHook con **Añadir…**. Usa estas descripciones: Dolphin
   nombra los dispositivos con ellas.

   | Descripción | Dirección | Puerto | Lleva |
   |---|---|---|---|
   | `WiiChinaHook` | `127.0.0.1` | `26760` | Botones, stick/C/Z del Nunchuk, acelerómetro y giroscopio del mando |
   | `WiiChinaHook Nunchuk` | `127.0.0.1` | `26762` | El acelerómetro del Nunchuk (opcional) |
   | `WiiChinaHook IR` | `127.0.0.1` | `26763` | El puntero de la cámara IR (opcional) |

   Puede que la lista ya traiga `DS4Windows` en `127.0.0.1:26760`. Es la misma dirección
   que el primer servidor, así que puedes dejarlo o sustituirlo por `WiiChinaHook`.
4. Cierra la ventana.

Un slot DSU lleva un solo sensor de movimiento y nada de IR, por eso el Nunchuk y el
puntero IR tienen sus propios servidores. Se activan o desactivan en WiiChinaHook:
pestaña *Mando Xbox* → editar el modo DSU → *Servidores DSU adicionales* (los dos
activados por defecto). Los puertos están en *Ajustes → Red*.

Dolphin pide a cada servidor sus slots cada segundo. Con WiiChinaHook en marcha, los
dispositivos aparecen como `DSUClient/<slot>/<descripción>`. Por ejemplo, el primer mando
(slot 0, LED 1) da `DSUClient/0/WiiChinaHook`, `DSUClient/0/WiiChinaHook Nunchuk` y
`DSUClient/0/WiiChinaHook IR`.

**Varios dispositivos en un mismo mando.** Cada asignación puede usar un dispositivo
distinto. Haz clic derecho en un campo para abrir el editor avanzado, elige el
dispositivo en su lista y después la entrada. O escribe el nombre completo, p. ej.
`` `DSUClient/0/WiiChinaHook IR:Right X+` ``.

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

**Puntero.** Hay dos formas:

- **Con barra sensora: servidor IR (recomendado).** Apunta la cámara real, como en una
  Wii, sin deriva.
  1. En **Simulación de movimiento** (*Motion Simulation*), asigna el grupo **Point** al
     dispositivo IR:

     | Point | Entrada de `DSUClient/0/WiiChinaHook IR` |
     |---|---|
     | Up / Down | `Right Y+` / `Right Y-` |
     | Left / Right | `Right X-` / `Right X+` |
     | Hide | `Cross` (pulsado mientras la cámara no ve la barra) |

  2. En **Entrada de movimiento** (*Motion Input*), desmarca o borra el grupo **Point**.
     Si no, el cursor del giroscopio se impone al del IR.
  3. Si el cursor llega a los bordes de la pantalla demasiado pronto o demasiado tarde,
     cambia el *Rango IR* en los ajustes del modo DSU de WiiChinaHook (más pequeño =
     menos movimiento para toda la pantalla).

  El stick conserva la última posición cuando la barra sale del campo de la cámara, y
  `Cross` le indica a Dolphin que oculte el cursor, como en una Wii real. *Hide* existe
  en las versiones recientes de Dolphin. Sin él, el cursor se queda en el último punto.
- **Sin barra sensora: giroscopio.**
  1. Deja activado el grupo **Point** de **Entrada de movimiento**, y sin asignar el
     *Point* de Simulación de movimiento.
  2. Asigna **Recenter** (recentrar) a una entrada que el juego no use. Una buena opción
     es − y + a la vez: en el editor avanzado, escribe `` `Share` & `Options` ``.
  3. Apunta al centro de la pantalla y púlsalo cuando el cursor se desvíe.
  4. Ajusta *Total Yaw* / *Total Pitch* (cuánto giras para recorrer la pantalla) a tu
     gusto.

Si el ratón también mueve el cursor, quita sus asignaciones del grupo *Point* de
Simulación de movimiento.

**Sacudidas:** con el acelerómetro real asignado, agitar el mando funciona como en una
Wii. Deja vacío el grupo *Shake* de *Simulación de movimiento*, o asígnalo a un botón
para juegos que piden sacudidas muy fuertes.

### Movimiento del Nunchuk (servidor Nunchuk)

El acelerómetro del Nunchuk llega por el servidor `WiiChinaHook Nunchuk`, como el
acelerómetro de ese dispositivo. En la pestaña **Extension Motion Input** del Nunchuk,
asigna su **Accelerometer** a `DSUClient/0/WiiChinaHook Nunchuk`:

| Accelerometer | Entrada |
|---|---|
| Up / Down | `Accel Up` / `Accel Down` |
| Left / Right | `Accel Left` / `Accel Right` |
| Forward / Backward | `Accel Forward` / `Accel Backward` |

Deja vacío **Extension Motion Simulation → Shake**, para que se usen las sacudidas reales
(ataques giratorios, etc.).

**Comprobaciones:**

- Quieto y plano, el indicador muestra la gravedad hacia abajo.
- El Nunchuk se lee sin calibrar, así que los movimientos muy suaves pueden diferir un
  poco de una Wii real. Las sacudidas y las inclinaciones funcionan.
- Los ejes son los mismos que los del mando, pero no se han comprobado con este Nunchuk.
  Si una dirección va al revés, intercambia ese par de asignaciones.

Si desactivas el servidor del Nunchuk, asigna el **Shake** del Nunchuk en **Extension
Motion Simulation** a un botón, p. ej. `` `Pad S` `` o `` `L1` & `L2` `` (C + Z).

Guarda el perfil (*Perfil* → nombre → *Guardar*) para cargarlo en otros juegos y mandos.

## 4. Más mandos

Funcionan hasta cuatro mandos a la vez. Cada uno tiene los mismos tres dispositivos, con
su propio índice, en los tres servidores:

| Dolphin | Mando (LED) | Dispositivos |
|---|---|---|
| Wii Remote 1 | slot 0 (LED 1) | `DSUClient/0/WiiChinaHook`, `DSUClient/0/WiiChinaHook Nunchuk`, `DSUClient/0/WiiChinaHook IR` |
| Wii Remote 2 | slot 1 (LED 2) | `DSUClient/1/…` (los mismos tres) |
| Wii Remote 3 | slot 2 (LED 3) | `DSUClient/2/…` |
| Wii Remote 4 | slot 3 (LED 4) | `DSUClient/3/…` |

El índice sigue el slot de WiiChinaHook (el LED que muestra el mando), no el orden en que
enciendes los mandos.

Los perfiles de Dolphin guardan los nombres de los dispositivos. Lo más rápido:

1. Configura el *Wii Remote 1* y guárdalo como perfil (p. ej. `WiiChinaHook 1`).
2. Cárgalo en el *Wii Remote 2*.
3. Cambia el índice de `0` a `1` en la lista **Dispositivo** y en cada asignación que nombre
   un dispositivo (el movimiento del Nunchuk y el Point IR). Guárdalo como `WiiChinaHook 2`.
4. Haz lo mismo con los mandos 3 y 4.

## Problemas frecuentes

| Síntoma | Solución |
|---|---|
| No aparece ningún `DSUClient` | ¿WiiChinaHook está en marcha? ¿El cliente DSU está activado con el puerto correcto? Solo un programa puede usar el puerto 26760 (cierra DS4Windows/BetterJoy o cambia el puerto). |
| El dispositivo aparece pero nada se mueve | WiiChinaHook no está en el modo DSU: cambia con B + → (o desde la GUI). |
| El dispositivo se desconecta una y otra vez | Actualiza WiiChinaHook (corregido en esta versión) y después quita y vuelve a añadir el servidor. |
| El movimiento va al revés o en espejo | Asignaciones intercambiadas. Revisa la tabla de arriba y pon el mando quieto boca arriba. |
| El cursor se desvía | Con barra sensora, usa el servidor IR (arriba). Con el cursor del giroscopio, asigna **Recenter**; la calibración rápida de WiiChinaHook (pestaña *Mandos*) también renueva el sesgo del giroscopio. |
| No aparecen los dispositivos `WiiChinaHook Nunchuk` / `IR` | Servidor desactivado en los ajustes del modo DSU, con el puerto en 0 u ocupado (*Ajustes → Red*; el registro lo indica), o no añadido en Dolphin. |
| El cursor IR se queda fijo o salta al centro | Quita las asignaciones del grupo **Entrada de movimiento → Point** (se impone al servidor IR). Comprueba que la cámara IR ve dos puntos en la pestaña *Mandos* de WiiChinaHook. |
| El cursor IR va al revés en vertical | Intercambia `Right Y+` / `Right Y-` en Point (el sentido vertical del IR aún no está comprobado con el mando). |
| El giroscopio no hace nada | Mando sin MotionPlus, o MotionPlus sin activar (la pestaña *Mandos* muestra "MotionPlus"). |

Ver también: [guía de Cemu](cemu.es.md) · [README](../../README.es.md)
