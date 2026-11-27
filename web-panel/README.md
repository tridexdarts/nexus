# web-panel — run commands without a terminal

For users who have never seen a terminal. Open

    http://<board-ip>:8080/

log in with the admin account (`tridex`) and its password, and either

- **paste a command** — e.g. the install line copied from a vendor's website
  (`curl -fsSL autodarts.sh | bash -s -- --headless` from
  autodarts.com/downloads) — and press "Ausführen", or
- **press a button** for a predefined command ("Schnellaktionen"), or
- **switch the LED ring** on or off and see which camera ports have a camera.

Either way the page shows "Fertig" or "Fehlgeschlagen" and the output, live.

A small link at the bottom leads advanced users to the
[browser terminal](../web-terminal/) on port 7681.

## Login

Accounts are the board's own (`/etc/shadow`, checked with libcrypt via
ctypes — Python 3.13 has no `crypt` module and no PAM binding in the
standard library). Only members of the `sudo` group may log in, never root.
Sessions are an in-memory cookie (HttpOnly, SameSite=Strict): logged out
after 30 minutes idle, 12 hours at most, and on every service restart.
5 wrong passwords from one address lock it out for 5 minutes.

## Who runs what

| | Runs as | Shell | Directory |
|---|---|---|---|
| Pasted command | `nexus-software` | `bash -c` (so `bash <(curl …)` works) | `/home/nexus-software` |
| Autodarts | `nexus-software` | — | `/home/nexus-software` |
| Button | root | `sh -c` | `/` |
| The panel itself | root | | |

`nexus-software` is a system user (created by the package via sysusers) with
no sudo, no password and no login shell; its group `video` gives Autodarts
the cameras. Third-party software lives there instead of under the admin
account: under `tridex` an installer or a compromised app could change
`~/.bashrc` or alias `sudo` and catch the admin password the next time it is
typed. Installers like Autodarts' need no sudo and install into `~/.local`,
so they work unchanged. A pasted `sudo …` fails on purpose: admin work goes
through the buttons (commands only root can define) or the terminal.

Every command run is logged with the admin who started it
(`journalctl -u nexus-panel`). In the terminal, act as that user with
`sudo -u nexus-software bash`.

## Autodarts

The official installer (`curl -fsSL autodarts.sh | bash -s -- --headless`,
pasted into the command box) puts Autodarts into `~/.local` of
`nexus-software` and sets up no service. The panel's Autodarts card takes it
from there, with [nexus-autodarts.service](nexus-autodarts.service): a
system unit running `autodarts run` as `nexus-software`.

| Card shows | Buttons |
|---|---|
| Not installed | Link to autodarts.com/downloads, paste the Headless line below |
| App's own user service found (`~/.config/systemd/user/autodarts.service`) | Remove it, or Autodarts would run twice |
| Installed, no autostart | Automatisch starten (`enable --now`) · Nur jetzt starten (`start`, until reboot) |
| Autostart on | Neu starten · Stoppen · Autostart aus |
| Always when installed | Aktualisieren (`autodarts update` as the user, then restart if running) · log |

Why a system unit and not the app's user unit: it starts at boot without a
login (no `loginctl enable-linger`), the panel controls it as root, and its
name cannot collide with the app's own `autodarts.service` user unit. `ConditionPathExists`
makes systemd skip it while Autodarts is not installed.

The unit assumes the home is `/home/nexus-software`. Up to 0.1.0 Autodarts
ran per admin user as `nexus-autodarts@<user>`; the upgrade disables those
instances, and Autodarts is installed again from the panel.

## Board card

With [nexus-board](../board/README.md) installed, the "Board" card switches
the LED ring and shows which camera port has a camera. The panel only talks
to `nexus-board`'s socket; the GPIOs belong to that service. Without it the
card says it is not installed.

## Adding a button

Edit `/etc/nexus/actions.json` on the board (root only). Changes show up on
the next page load, no restart needed.

```json
[
  {
    "id": "reboot",
    "title": "Nexus neu starten",
    "description": "Hilft, wenn etwas hängt. Dauert etwa eine Minute.",
    "command": "echo 'Nexus startet jetzt neu. …'; systemctl --no-block reboot",
    "confirm": "Nexus jetzt neu starten? Autodarts ist dabei kurz nicht erreichbar."
  },
  {
    "id": "install-htop",
    "title": "htop installieren",
    "description": "Installiert den Prozess-Monitor.",
    "command": "apt-get update && apt-get install -y htop",
    "confirm": "htop jetzt installieren?",
    "timeout": 1800
  }
]
```

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Unique, used in the URL |
| `title` | yes | Button label |
| `command` | yes | Run as root with `/bin/sh -c`, working directory `/` |
| `description` | no | Grey line under the title |
| `confirm` | no | Asks this yes/no question before running |
| `timeout` | no | Seconds until the command is stopped (default 1800) |

Commands run non-interactively (`DEBIAN_FRONTEND=noninteractive`, no
stdin): anything that asks a question must be told the answer, e.g. `-y`.
Output (stdout and stderr) appears live; exit code 0 means "Fertig".

## Install

Packaged as `nexus-web-panel` (see [packaging/apt/](../packaging/apt/README.md)):

```bash
sudo apt install nexus-web-panel        # or "nexus" for everything
```

| File | Installed to |
|---|---|
| `nexus-panel.py` | `/usr/lib/nexus-panel/` |
| `static/` + the captive portal's stylesheet, font and logo | `/usr/share/nexus-panel/static/` |
| `actions.json` | `/usr/share/nexus-panel/`, copied to `/etc/nexus/actions.json` if that is missing — never overwritten afterwards |
| `nexus-panel.service` | `/usr/lib/systemd/system/` (enabled and started on install) |
| `nexus-autodarts.service` | `/usr/lib/systemd/system/` (not enabled: the Autodarts card does that) |

The package also creates the user `nexus-software` (sysusers) and its home
`/home/nexus-software` (tmpfiles).

Python standard library only.

## Things to know

- **Plain HTTP.** The password crosses the LAN unencrypted — fine on a
  home Wi-Fi with WPA2/3, not on a shared network.
- **No questions.** Commands get no input (stdin is empty, no terminal).
  Installers must be told their answers via flags — for Autodarts that is
  the `--headless` in the copied line.
- **Not reachable from the setup hotspot** (10.41.0.0/24 denied, as for the
  terminal).
- **Port 8080**, because comitup's portal holds port 80 while the hotspot is up.
- **One command at a time.** A second click while one runs gets a message
  instead of a second `apt` fighting over the lock. Closing the tab does not
  stop a running action.
- Requests from other websites are refused (the page sends an
  `X-Nexus-Panel` header that cross-site requests cannot add).

## Debugging

```bash
systemctl status nexus-panel
journalctl -u nexus-panel -f     # which action ran, with exit code
journalctl -u nexus-autodarts -f
systemctl status nexus-autodarts
```
