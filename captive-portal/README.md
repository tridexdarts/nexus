# captive-portal — Wi-Fi setup

How the board gets onto Wi-Fi: if it boots and cannot join a known network, it
opens its own hotspot. Any phone or laptop that joins it gets a captive portal
listing nearby networks, picks one, enters the password, and the board joins.
On a fresh board the portal first asks for the password of the admin account
`tridex`, so no board ever runs with a default password.

It is built on [comitup](https://github.com/davesteele/comitup), which is in
Debian main — so the moving parts (hotspot, DHCP/DNS, firewall) get security
updates through `apt`. The portal web app is our own (`lib/nexus-portal`):
comitup's runs as root and has no place for the password step.

## Flow

```
boot
 │
 ├─ known Wi-Fi reachable? ── yes ──> connect, done
 │
 no
 │
 └─> hotspot "Nexus-<nnn>" + portal at http://10.41.0.1/      Wi-Fi LED blinks slowly
       │
       ├─ tridex still locked ("*")? ── yes ──> set its password first
       │
       │  user picks network, enters password
       ▼
     hotspot goes down, board tries the network
       │
       ├─ fails ──> hotspot comes back, user tries again
       │
       └─ works ──> network saved in NetworkManager, board reboots once
                    (bin/nexus-comitup-callback), comes up on the new network
```

The reboot is not needed for the Wi-Fi itself; comitup switches live. It is
there so everything on the board starts clean on the new network. To drop it,
remove `external_callback` from `etc/comitup.conf` and release.

## Admin password

The image ships `tridex` **locked** (`*` in `/etc/shadow`): no password
matches, so nobody can log in to the panel, terminal or SSH with a password.
Do not ship it *empty* instead: Debian's PAM accepts an empty password
(`nullok`), so the web terminal would let anyone on the LAN in.

Who does what:

| Part | Runs as | Can |
|---|---|---|
| `nexus-portal` (comitup-web.service) | `nexus-portal`, only `CAP_NET_BIND_SERVICE`, reachable only from `10.41.0.0/24` | serve the pages, call comitup over D-Bus, talk to the helper socket |
| `nexus-initpw` (nexus-initpw.socket → `nexus-initpw@.service`) | root, sandboxed, no network | report whether `tridex` has a password; set it **only while it is `*`, `!` or empty** |

The account name is fixed in the helper, never sent by the client, and a set
password cannot be changed through it. Only group `nexus-portal` may connect
to `/run/nexus-initpw.sock`. Rules: 8–128 characters, no control characters.
`/confirm` and `/connect` refuse until the password is set, so the step cannot
be skipped by typing a URL. A board that already knows a Wi-Fi network never
shows the portal, so it keeps `tridex` locked until the Wi-Fi reset below.

Changing a known password: `passwd` in the web terminal.

## Wi-Fi LED and reset button

`nexus-wifi-button.service` owns two GPIOs (pins in the unit's `Environment=`):

| | Line | Level |
|---|---|---|
| Wi-Fi reset button | `gpiochip4` 13 (GPIO4_B5) | 0 = pressed |
| Wi-Fi LED | `gpiochip4` 12 (GPIO4_B4) | 1 = on |

| LED | Meaning |
|---|---|
| slow blink (1 s / 1 s) | hotspot up, setup needed |
| on | connected to Wi-Fi |
| off | connecting, or comitup not running; also while the button is held |
| fast blink | button held 10 s: release now to reset |

**Forgotten password:** hold the button until the LED blinks fast (10 s; also
works when held while the board boots, it then takes longer), release.
`nexus-access-reset.service` then locks `tridex` again (`*`), deletes its
`~/.ssh/authorized_keys`, deletes every saved Wi-Fi network and reboots. The
board comes up in the hotspot and the portal asks for a new password, as on a
new board. A shorter press does nothing. Autodarts and eth0 are not touched.
As root, `nexus-access-reset` does the same by hand.

Both lines belong to the service: `sudo systemctl stop nexus-wifi-button`
before testing them with `gpioset`/`gpioget`.

## Contents

Packaged as `nexus-captive-portal` (see [packaging/apt/](../packaging/apt/README.md)).

| Path | Installed to | Purpose |
|---|---|---|
| `etc/comitup.conf` | `/usr/share/nexus/comitup.conf`, linked from `/etc/comitup.conf` | Hotspot name, password, callback |
| `templates/` | `/usr/share/nexus/comitup-templates/` | Portal pages (German) and CSS |
| `lib/nexus-portal` | `/usr/lib/nexus-captive-portal/` | Portal web app (Flask), unprivileged |
| `lib/nexus-initpw` | `/usr/lib/nexus-captive-portal/` | Root helper: first password of `tridex` only |
| `lib/nexus-wifi-button` | `/usr/lib/nexus-captive-portal/` | Wi-Fi LED and reset button |
| `bin/nexus-access-reset` | `/usr/sbin/` | Lock `tridex`, delete its SSH keys and saved Wi-Fi, reboot |
| `bin/nexus-comitup-callback` | `/usr/sbin/` | Reboots once after provisioning via the portal |
| `systemd/comitup-web.service.d/nexus-portal.conf` | `/usr/lib/systemd/system/…` | comitup-web runs `nexus-portal` as user `nexus-portal` |
| `systemd/nexus-initpw.socket`, `nexus-initpw@.service` | `/usr/lib/systemd/system/` | Helper socket (group `nexus-portal`), one root instance per request |
| `systemd/nexus-wifi-button.service` | `/usr/lib/systemd/system/` | Enabled; GPIO pins in `Environment=` |
| `systemd/nexus-access-reset.service` | `/usr/lib/systemd/system/` | Not enabled, never started by package scripts |

The user `nexus-portal` comes from `debian/nexus-captive-portal.sysusers`.
The package's maintainer scripts ([debian/](../debian/)) divert comitup's own
`/etc/comitup.conf` and hand wlan0 to NetworkManager — details in
[packaging/apt/README.md](../packaging/apt/README.md#what-the-captive-portal-package-does-to-the-system).

## Install

On the board, over Ethernet:

```bash
sudo apt install nexus-captive-portal        # or "nexus" for everything
```

Changes to anything here reach the boards with the next release. Before the
first install, check:

```bash
cat /etc/os-release                                  # Debian base of Radxa OS
nmcli dev status                                     # wlan0 must be managed by NetworkManager
iw list | grep -A8 "Supported interface modes"       # must list "AP"
apt-cache policy comitup                             # package available?
```

## Customising the portal

The pages are Jinja2 templates rendered by `lib/nexus-portal`. Change looks
and wording freely; keep the contract with the app:

| Page | Gets | Must send |
|---|---|---|
| `password.html` | `user`, `error` (message or none), `min_length` | `POST password` with `password` and `password2` |
| all pages | `first_setup`: password set through the portal since it started, so the Wi-Fi pages are step 2 of 2 | — |
| `index.html` | `points`: list of `ssid`, `ssid_encoded`, `security`, `strength` (%) | links to `confirm?ssid=<ssid_encoded>&encrypted=<security>` |
| `confirm.html` | `ssid`, `ssid_encoded`, `encrypted`, `mode` (`single`/`router`) | `POST connect` with `ssid` (URL-encoded) and `password` |
| `connect.html` | `ssid` | — |

Static files go under `templates/css/`, `templates/js/` and
`templates/images/`, served as `/css/…`, `/js/…` and `/img/…`.

**Design.** The pages follow the Tridex corporate design of
[tridexdarts.com](https://tridexdarts.com/): its dark theme tokens
(`#0a0a0a` background, `#171717` cards, `#e0202d` brand red, `0.75rem`
radius), Montserrat, the uppercase "eyebrow" labels and the angled CTA buttons.
`images/logo.svg` and `images/icon.svg` are the website's logo and favicon.
The hotspot has no internet, so everything is served locally — no CDN fonts.
`css/montserrat-latin.woff2` is the website's Latin subset of Montserrat
(SIL Open Font License 1.1, `css/OFL.txt` must ship alongside it).

The portal talks to comitup only over its D-Bus API (`access_points`,
`get_info`, `connect`). After a comitup upgrade, open the portal once: if
upstream changed that API, `lib/nexus-portal` needs adjusting.

## Things to know

- **The network list is a snapshot.** A single radio cannot scan while it serves
  a hotspot, so comitup scans just before starting it. A network switched on
  later only appears after the hotspot cycles.

- **Port 53.** comitup runs its own dnsmasq for the hotspot. If
  `systemd-resolved` or another DNS server listens on `0.0.0.0:53`, the hotspot
  DNS fails and the portal does not pop up.
- **DietPi.** The board runs DietPi, which normally owns networking through
  ifupdown and `dietpi-config`. The package hands wlan0 to NetworkManager and
  leaves eth0 with ifupdown. Do not use the network settings in `dietpi-config`
  afterwards: it rewrites `/etc/network/interfaces`, re-adds the wlan0 stanza,
  and comitup loses the radio. Re-install the package (`sudo apt install --reinstall nexus-captive-portal`) if that happened.
- **Open hotspot.** Anyone nearby can provision an unconfigured board, and
  whoever is first also sets the admin password. Set `ap_password` if that
  matters. From the Ethernet side the portal is unreachable (`IPAddressDeny`).

## Debugging

```bash
journalctl -u comitup -u comitup-web -f     # comitup and the portal
journalctl -u 'nexus-initpw@*'              # password helper
journalctl -u nexus-wifi-button -t nexus-access-reset   # button, LED, reset
journalctl -t nexus-comitup                 # the reboot callback
comitup-cli                                 # state, saved networks, delete them
nmcli connection show                       # what NetworkManager has saved
```

For detail in `/var/log/comitup.log`, set `verbose: 1` in `/usr/share/nexus/comitup.conf` on the board and `systemctl restart comitup` (the next package upgrade resets it).
To force the hotspot again, delete the saved Wi-Fi with `comitup-cli` (or
`nmcli connection delete <name>`) and reboot — or use the reset button, which
also locks `tridex`. To test the password step on a board: `sudo usermod -p '*' tridex`.
