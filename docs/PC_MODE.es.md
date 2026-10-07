# Modo PC (ratón y teclado)

*[English](PC_MODE.md) · Español*

En el modo PC los mandos controlan el propio Windows: ratón, atajos de teclado, teclas
multimedia y lanzadores. No se crea ningún mando Xbox virtual, así que funciona en
cualquier programa o juego que use ratón y teclado.

El modo 3 es el modo PC por defecto (mantén **B** y pulsa **↓** en el mando). Cualquier
modo puede convertirse en modo PC en la pestaña *Mando Xbox* → *Editar modo* → *Tipo de
modo*.

## Ratón

Elige qué mueve el puntero:

| Fuente | Cómo se mueve | Ajustes |
|---|---|---|
| Giroscopio (por defecto) | Gira el mando. Como un ratón aéreo: el puntero se mueve mientras giras | Píxeles por grado; zona muerta en °/s (oculta la deriva residual y el temblor) |
| Puntero IR | Apunta a la barra sensora: el puntero va donde apuntas | Rango IR (cuánto del campo de la cámara cubre la pantalla); suavizado |
| Stick del Nunchuk | Empuja el stick. Una curva da precisión cerca del centro | Píxeles por segundo al máximo; zona muerta |
| Cruceta del Wiimote | Mantén una flecha. Empieza lento y luego acelera | Píxeles por segundo |
| Nada | — | — |

Lo que mueve el ratón **no se puede mapear también**. Con la cruceta o el stick del
Nunchuk como ratón, sus filas quedan desactivadas en el editor y la configuración las
rechaza.

Con el giroscopio, la calibración rápida (pestaña *Mandos*) elimina la deriva. Si el
puntero sigue moviéndose solo, sube un poco la zona muerta.

## Acciones

Cada entrada puede hacer una cosa:

| Tipo | Ejemplo | Comportamiento |
|---|---|---|
| **Teclas** | `ctrl+9`, `ctrl+shift+esc`, `win+d`, `alt+f4` | Cualquier número de teclas. Se mantienen pulsadas mientras mantienes el botón y se sueltan en orden inverso |
| **Ratón** | clic izquierdo, derecho o central; rueda arriba o abajo | Los clics se mantienen (se puede arrastrar); la rueda se repite mientras mantienes |
| **Sistema** | silenciar, subir/bajar volumen, pista siguiente/anterior, reproducir/pausa, detener, menú Inicio | Se ejecuta una vez por pulsación |
| **Abrir** | `notepad`, `C:\Juegos\juego.exe`, `https://example.com` | Abre un programa, archivo o página web una vez por pulsación |
| **Alternar** | `ctrl+c \| ctrl+v`, `system:mute \| system:mute` | Cada pulsación ejecuta el siguiente paso; tras el último vuelve a empezar |

Las entradas que puedes mapear:

- **Wiimote:** A, B, 1, 2, −, +, Home y la cruceta.
- **Nunchuk:** C, Z y **el stick como cuatro botones** (↑ ↓ ← →; empujado más de la mitad).
- **Sacudidas:** del mando o del Nunchuk en un eje.

**Nombres de teclas:** `a`–`z`, `0`–`9`, `f1`–`f24`, `ctrl`, `shift`, `alt`, `win`, `enter`,
`esc`, `tab`, `space`, `backspace`, `delete`, `insert`, `home`, `end`, `pageup`, `pagedown`,
`up`, `down`, `left`, `right`, `capslock`, `printscreen`, `menu`, `num0`–`num9`, `num_add`,
`num_subtract`, `num_multiply`, `num_divide`, `num_decimal`, `num_enter`, `;` `=` `,` `-` `.`
`/` `` ` `` `[` `\` `]` `'`, y los derechos `rctrl`, `rshift`, `ralt`, `rwin`. También valen
alias comunes (`control`, `escape`, `del`, `pgup`…), en mayúsculas o minúsculas.

**Los pasos de Alternar** se separan con `|`. Un paso es teclas (sin prefijo), `mouse:…`,
`system:…` u `open:…`, p. ej. `toggle:ctrl+c | ctrl+v` o
`toggle:open:notepad | keys:alt+f4`.

## Valores por defecto

| Entrada | Acción |
|---|---|
| A / B | Clic izquierdo / derecho |
| Cruceta | Flechas del teclado |
| − / + | Bajar / subir volumen |
| Home | Menú Inicio |
| 1 | `alt+tab` (mantén para dejar abierto el selector) |
| 2 | Reproducir / pausa |
| C / Z | Clic central / Enter |
| Stick del Nunchuk ↑ / ↓ | Rueda arriba / abajo |
| Stick del Nunchuk ← / → | `alt+left` / `alt+right` (atrás / adelante) |

## Detalles

- **Cambiar de modo sigue funcionando:** modificador (B) + flecha. En el modo PC, la
  acción del modificador se ejecuta **al soltarlo**, y solo si no cambiaste de modo.
  B + flecha nunca hace clic derecho.
- **Los botones que ya estaban pulsados al empezar el modo** (p. ej. el B + ↓ que lo
  eligió) se ignoran hasta que los sueltas.
- **Nada se queda pulsado:** al cambiar de modo, cambiar la configuración o
  desconectarse un mando, se sueltan todas las teclas y botones del ratón que tuviera.
- **Varios mandos** pueden estar en modo PC a la vez. Todos manejan el mismo puntero y
  teclado.
- **Las teclas también llegan a los juegos:** se envían como códigos de escaneo, que ven
  también los juegos que leen la entrada directa. Windows no deja que un programa normal
  envíe entradas a otro que se ejecuta como administrador. Para esos, ejecuta también
  WiiChinaHook como administrador.
- **`open:` usa el shell de Windows**, como un doble clic. Pon ahí solo programas de
  confianza. La configuración se puede cambiar por la API local, a la que solo se
  accede desde este PC.
