def dsu_buttons_from_wiimote(buttons: int) -> tuple[int, int, int, bytes]:
    dpad = 0
    face = 0
    home = 0

    if buttons & 0x0100:
        dpad |= 0x80
    if buttons & 0x0400:
        dpad |= 0x40
    if buttons & 0x0200:
        dpad |= 0x20
    if buttons & 0x0800:
        dpad |= 0x10
    if buttons & 0x1000:
        dpad |= 0x08
    if buttons & 0x0010:
        dpad |= 0x01

    if buttons & 0x0002:
        face |= 0x80
    if buttons & 0x0001:
        face |= 0x40
    if buttons & 0x0008:
        face |= 0x20
    if buttons & 0x0004:
        face |= 0x10
    if buttons & 0x0080:
        home = 1

    analogs = bytearray(12)
    for index, pressed in enumerate(
        [
            bool(dpad & 0x80),
            bool(dpad & 0x40),
            bool(dpad & 0x20),
            bool(dpad & 0x10),
            bool(face & 0x80),
            bool(face & 0x40),
            bool(face & 0x20),
            bool(face & 0x10),
            False,
            False,
            False,
            False,
        ]
    ):
        analogs[index] = 255 if pressed else 0

    return dpad, face, home, bytes(analogs)
