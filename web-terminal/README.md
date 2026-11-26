# web-terminal — a terminal in the browser

Once the board is on the network, open

    http://<board-ip>:7681/

The page is just a terminal. Log in with a system account, then type commands,
e.g. `sudo apt install <program>`. Nothing else to learn.

It is [ttyd](https://github.com/tsl0922/ttyd) running `login`. ttyd is not in
Debian trixie, so the package carries the upstream static build, pinned to a
version and SHA-256 in [debian/rules](../debian/rules). To update ttyd, bump
`TTYD_VERSION`/`TTYD_SHA256` there and release.

## Install

Packaged as `nexus-web-terminal` (arm64; see [packaging/apt/](../packaging/apt/README.md)):

```bash
sudo apt install nexus-web-terminal     # or "nexus" for everything
```

| File | Installed to |
|---|---|
| ttyd 1.7.7 (`ttyd.aarch64`) | `/usr/lib/nexus-web-terminal/ttyd` |
| `nexus-web-terminal.service` | `/usr/lib/systemd/system/` (enabled and started on install) |

## Things to know

- **Not reachable from the setup hotspot.** The hotspot is open, so the
  service denies 10.41.0.0/24 (`IPAddressDeny`, enforced by the kernel).
  Over Ethernet it stays reachable while the hotspot is up.
- **Plain HTTP.** No certificate warning for users, but the login password
  crosses the LAN unencrypted. Fine on a home Wi-Fi with WPA2/3; on a shared
  network add `--ssl --ssl-cert … --ssl-key …` to the service.
- **Change the default passwords** (user and root). Anyone on the LAN who
  knows one gets a shell, and with `sudo` a root shell.

## Debugging

```bash
systemctl status nexus-web-terminal
journalctl -u nexus-web-terminal -f
```
