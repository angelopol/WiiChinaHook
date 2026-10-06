# Third-party notices

WiiChinaHook is released under the [MIT License](LICENSE). The release executables
bundle the components below, each under its own license. Their license texts are
included in the bundle's `_internal` folder (in each package's `*.dist-info`) and at the
linked projects.

| Component | Version | License | Project |
|---|---|---|---|
| Python | 3.13 | PSF-2.0 | https://www.python.org |
| Bumble | 0.0.235 | Apache-2.0 | https://github.com/google/bumble |
| Flet, flet-desktop (Flutter client) | 1.0.3 | Apache-2.0 (Flutter: BSD-3-Clause) | https://github.com/flet-dev/flet |
| websockets | 17.2 | BSD-3-Clause | https://github.com/python-websockets/websockets |
| cython-hidapi (`hidapi`) | 0.15.0 | used under its BSD option (also GPL-3.0) | https://github.com/trezor/cython-hidapi |
| PyUSB | 1.3.1 | BSD-3-Clause | https://github.com/pyusb/pyusb |
| python-libusb1 | 3.4.0 | LGPL-2.1-or-later | https://github.com/vpelletier/python-libusb1 |
| libusb-package (`libusb-1.0.dll`) | 1.0.26.4 | Apache-2.0 (libusb: LGPL-2.1-or-later) | https://github.com/pyocd/libusb-package |
| vgamepad | 0.1.0 | MIT | https://github.com/yannbouteiller/vgamepad |
| ViGEmClient (`ViGEmClient.dll`, via vgamepad) | — | MIT | https://github.com/nefarius/ViGEmClient |
| ViGEmBus installer (via vgamepad) | — | BSD-3-Clause | https://github.com/nefarius/ViGEmBus |
| pystray | 0.19.5 | LGPL-3.0 | https://github.com/moses-palmer/pystray |
| Pillow | 12.3.0 | MIT-CMU | https://github.com/python-pillow/Pillow |
| six | 1.17.0 | MIT | https://github.com/benjaminp/six |
| PyInstaller bootloader | 6.22.3 | GPL-2.0-or-later with the bootloader exception (allows any license for the bundled app) | https://github.com/pyinstaller/pyinstaller |

## LGPL components

python-libusb1, libusb and pystray are LGPL. The release is a folder (not a single
packed file), so these libraries ship as separate, replaceable files: `libusb-1.0.dll`
and the Python packages under `_internal`. You can swap in a modified version of any of
them. Their source code is available at the links above. To rebuild WiiChinaHook
itself, run `tools/build_release.ps1` from this repository.

## Trademarks

Wii, Wii Remote, Nunchuk, MotionPlus and Wii U are trademarks of Nintendo. Xbox is a
trademark of Microsoft. DolphinBar is a product of Mayflash. WiiChinaHook is not
affiliated with or endorsed by any of them. It only talks to hardware you own over
standard USB/Bluetooth/HID interfaces.

Dolphin's source code (GPL-2.0-or-later) was read to document the axis conventions of
its DSU client. No Dolphin code is included.
