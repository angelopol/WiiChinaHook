# Cemu con el modo DSU

*[English](cemu.md) · Español*

Cemu lee mandos por DSU y usa los datos de movimiento para el **giroscopio del Wii U
GamePad** (apuntar en Splatoon, santuarios de BotW, etc.) y para los Wii Remotes
emulados. Esta guía usa los botones, el Nunchuk, el acelerómetro y el giroscopio
MotionPlus del mando.

## 1. Pon WiiChinaHook en el modo DSU

1. Abre WiiChinaHook y conecta el mando.
2. Cambia al **modo 2 (DSU)**: mantén **B** y pulsa **→** en el mando (dos vibraciones,
   parpadea el LED 2), o pulsa *Modo 2* en la pestaña *Mando Xbox*.

En los demás modos los mandos siguen apareciendo, pero no envían entradas. El servidor
escucha en `127.0.0.1:26760`.

## 2. Añade el mando en Cemu

1. **Opciones** → **Ajustes de entrada** (*Input settings*).
2. Elige el **mando emulado** del *Controller 1*:
   - **Wii U GamePad** para la mayoría de juegos. El giroscopio apunta o dirige.
   - **Wiimote** para juegos compatibles con Wii Remotes (p. ej. New Super Mario Bros. U,
     Mario Kart 8). Elige la extensión *Nunchuk* si la usas.
3. Pulsa **+** (añadir mando). En **API**, elige **DSUController**.
4. Pulsa el botón de **ajustes** junto a la API y comprueba **IP** `127.0.0.1` y
   **Puerto** `26760`.
5. En **Controller**, elige **Controller 1** (= slot 0 de WiiChinaHook, LED 1) y pulsa
   **Add**.
6. Abre los **Ajustes** de ese mando y marca **Use motion**. Sin esta opción, Cemu
   ignora el acelerómetro y el giroscopio.

## 3. Asigna los botones

Pulsa cada campo y después el botón en el mando. Cemu guarda lo que recibe, así que la
tabla de abajo es solo una distribución sugerida. Entre paréntesis están las entradas
DSU que Cemu registra.

### Como Wii U GamePad

El mando solo tiene pocos botones. Con Nunchuk cubre casi todo un GamePad:

| GamePad | Mando | Entrada DSU |
|---|---|---|
| A / B | A / B | `Circle` / `Triangle` |
| X / Y | 1 / 2 | `Square` / `Cross` |
| L / ZL | C / Z | `L1` / `L2` |
| + / − | + / − | `Options` / `Share` |
| Home | HOME | `PS` |
| Cruceta | Cruceta | `Pad N/S/W/E` |
| Stick izquierdo | Stick del Nunchuk | `Left X` / `Left Y` |

R, ZR y el stick derecho no tienen ninguna entrada libre. Si un juego los necesita, usa
una plantilla Xbox (modo 1 de WiiChinaHook). Ahí las combinaciones y las sacudidas
pueden sustituir a los botones que faltan.

### Como Wiimote

Asigna cada botón del Wiimote al mismo botón del mando (A → `Circle`, B → `Triangle`,
1 → `Square`, 2 → `Cross`, − → `Share`, + → `Options`, Home → `PS`, cruceta →
`Pad N/S/W/E`). Para la extensión Nunchuk: C → `L1`, Z → `L2`, stick → `Left X/Y`.

## 4. Movimiento

- **Use motion** tiene que estar marcado en los ajustes del mando (paso 2.6).
- Cemu usa directamente el acelerómetro y el giroscopio de DSU. Deja el mando quieto un
  momento tras conectarlo para que se asiente el sesgo del giroscopio. La calibración
  rápida de WiiChinaHook (pestaña *Mandos*) o `calibrate` eliminan la deriva restante.
- El movimiento del GamePad está pensado para una tableta sujeta con las dos manos. Con
  un mando, sujétalo **plano, botones arriba y punta hacia delante**, como la pantalla
  del GamePad. Así, inclinarlo y girarlo coincide con el GamePad.
- Cemu no puede usar la cámara IR por DSU. Los juegos de puntero usan el giroscopio, o
  el puntero del ratón si asignas uno.

## 5. Más mandos

Añade *Controller 2*, 3 o 4 con **Controller 2**, … (slots 1, 2 y 3 de WiiChinaHook) para
multijugador local. Cada uno necesita **Use motion** si el juego lee su movimiento.

## Problemas frecuentes

| Síntoma | Solución |
|---|---|
| "Controller 1" no aparece / no conectado | ¿WiiChinaHook está en marcha y el puerto coincide? Solo un servidor DSU puede ocupar el puerto 26760. |
| Los botones solo funcionan en el modo 2 | Es lo esperado: los demás modos dejan DSU sin entradas. |
| Sin giroscopio | **Use motion** desmarcado, o el mando no tiene un MotionPlus activo. |
| La puntería se desvía | Deja el mando quieto y haz la calibración rápida, o `calibrate` en la CLI. |

Ver también: [guía de Dolphin](dolphin.es.md) · [README](../../README.es.md)
