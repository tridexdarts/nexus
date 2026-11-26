# captive-portal — Wi-Fi setup

How the board gets onto Wi-Fi: if it boots and cannot join a known network, it
opens its own hotspot. Any phone or laptop that joins it gets a captive portal
listing nearby networks, picks one, enters the password, and the board joins.

It is built on [comitup](https://github.com/davesteele/comitup), which is in
Debian main — so the moving parts (hotspot, DHCP/DNS, firewall, web server) get
security updates through `apt`. This directory only holds configuration and the
portal's look.

## Flow

```
boot
 │
 ├─ known Wi-Fi reachable? ── yes ──> connect, done
 │
 no
 │
 └─> hotspot "Nexus-<nnn>" + portal at http://10.41.0.1/
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

## Contents

Packaged as `nexus-captive-portal` (see [packaging/apt/](../packaging/apt/README.md)).

| Path | Installed to | Purpose |
|---|---|---|
| `etc/comitup.conf` | `/usr/share/nexus/comitup.conf`, linked from `/etc/comitup.conf` | Hotspot name, password, callback |
| `templates/` | `/usr/share/nexus/comitup-templates/` | Portal pages (German) and CSS |
| `bin/nexus-comitup-callback` | `/usr/sbin/` | Reboots once after provisioning via the portal |

The package's maintainer scripts ([debian/](../debian/)) divert comitup's own
`/etc/comitup.conf`, generate the systemd drop-in
`/etc/systemd/system/comitup-web.service.d/nexus-templates.conf` that makes
comitup serve our templates, and hand wlan0 to NetworkManager — details in
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

The pages are Jinja2 templates rendered by comitup's Flask app. Change looks
and wording freely; keep the contract with the app:

| Page | Gets | Must send |
|---|---|---|
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

**Why a bind mount instead of editing comitup's own templates:** those
files are not conffiles, so `apt upgrade` would overwrite them silently. The
drop-in mounts our directory over theirs only inside `comitup-web.service`.
After a comitup upgrade, open the portal once — if upstream renamed template
variables or routes, the pages need adjusting.

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
- **Open hotspot.** Anyone nearby can provision an unconfigured board. Set
  `ap_password` if that matters.

## Debugging

```bash
journalctl -u comitup -u comitup-web -f     # comitup itself
journalctl -t nexus-comitup                 # the reboot callback
comitup-cli                                 # state, saved networks, delete them
nmcli connection show                       # what NetworkManager has saved
```

For detail in `/var/log/comitup.log`, set `verbose: 1` in `/usr/share/nexus/comitup.conf` on the board and `systemctl restart comitup` (the next package upgrade resets it).
To force the hotspot again, delete the saved Wi-Fi with `comitup-cli` (or
`nmcli connection delete <name>`) and reboot.
