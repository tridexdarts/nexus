# board — LED ring and camera port LEDs

`nexus-board.service` holds the Nexus PCB's LED GPIOs for as long as it runs.
With libgpiod v2 only the process holding a line can rely on its level, so a
short-lived `gpioset` (or a udev `RUN` script, which may not run long) cannot
keep an LED on.

| LED | GPIO (`gpiochip4`) | Behaviour |
|---|---|---|
| LED ring | line 8 | on/off on request; last state survives a reboot, a new board starts with it on |
| USB 1 (`5-1`) | line 10 | on while a camera is plugged in |
| USB 2 (`2-1`) | line 11 | on while a camera is plugged in |
| USB 3 (`3-1`) | line 9 | on while a camera is plugged in |

1 = LED on. The pins are set in the unit's `Environment=`
([nexus-board.service](nexus-board.service)); `NEXUS_CAMERA_PORTS` maps a
label to the port's USB path (as in `/sys/bus/usb/devices/`) and its LED line.

**Camera** means a USB device with a video interface (class `0x0e`, what UVC
webcams report) on that port, directly or behind a hub on it. A USB stick
does not light the LED. The ports are checked every second, so the LEDs are
right from boot on and after unplugging.

The Wi-Fi LED and the Wi-Fi reset button (lines 12, 13) belong to
`nexus-wifi-button` in [captive-portal/](../captive-portal/README.md#wi-fi-led-and-reset-button).

## Control

```bash
sudo nexus-board               # LED ring: on / USB 1: camera / USB 2: - …
sudo nexus-board ring off      # or on
```

It goes through `/run/nexus-board.sock` (`nexus-board.socket`), root only,
one request per line, JSON reply:

| Request | Reply |
|---|---|
| `status` | `{"ring": true, "cameras": [{"port": "USB 1", "camera": true}, …]}` (`ring` is `null` without GPIO) |
| `ring on`, `ring off` | the same, after switching |
| anything else | `{"error": "…"}` |

`nexus-software` (Autodarts) cannot switch the ring. To allow it later, give
the socket a group (`SocketGroup=`, `SocketMode=0660`) and add the user.

## Debugging

```bash
journalctl -u nexus-board -f              # ring switched, camera connected/gone
lsusb -t                                  # which port a camera sits on
cat /sys/bus/usb/devices/5-1:*/bInterfaceClass   # 0e = video
```

While the service runs, `gpioset` on lines 8–11 fails with "busy": `sudo
systemctl stop nexus-board` first.
