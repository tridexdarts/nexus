# Tridex Nexus — board software

Software for the Nexus PCB (Radxa CM3, DietPi / Debian trixie), shipped as
Debian packages from the apt repository
[tridexdarts/nexus-apt](https://github.com/tridexdarts/nexus-apt). Boards install it once
and then update with `apt upgrade`.

| Directory | Contents | Package |
|---|---|---|
| [captive-portal/](captive-portal/) | Wi-Fi setup: hotspot + captive portal via comitup, first admin password, Wi-Fi LED and reset button | `nexus-captive-portal` |
| [web-panel/](web-panel/) | Web page (port 8080) to paste commands or press buttons, for non-technical users | `nexus-web-panel` |
| [web-terminal/](web-terminal/) | Terminal in the browser (ttyd, port 7681) | `nexus-web-terminal` |
| [experiments/](experiments/) | USB-port → GPIO trigger via udev | — |
| [debian/](debian/) | Packaging: one source package, all binary packages | |
| [packaging/apt/](packaging/apt/) | apt repository: publishing, signing key, setup | `nexus-archive-keyring` |

`nexus` is the metapackage that pulls in everything packaged.

## Setting up a board

Over Ethernet (the captive portal takes wlan0 over from ifupdown):

```bash
curl -fsSLO https://tridexdarts.github.io/nexus-apt/nexus-archive-keyring.deb
sudo apt install ./nexus-archive-keyring.deb
sudo apt update
sudo apt install nexus
```

## Building locally

```bash
sudo apt install build-essential devscripts equivs
sudo mk-build-deps -i -r debian/control
dpkg-buildpackage -us -uc -b          # .debs land in the parent directory
```

## License

Copyright 2026 Tridex. Licensed under the GNU General Public License, version 3
or (at your option) any later version; see [LICENSE](LICENSE). Bundled
third-party parts (the Montserrat font, ttyd) keep their own licenses, listed
in [debian/copyright](debian/copyright).
