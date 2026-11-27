# Debian packages and the apt repository

The board software ships as Debian packages, built from [debian/](../../debian/)
and served as an apt repository on GitHub Pages. Boards update with
`apt upgrade`.

| Package | Arch | Contents |
|---|---|---|
| `nexus` | all | Metapackage: depends on the four below |
| `nexus-captive-portal` | all | comitup config, setup portal with first admin password, Wi-Fi LED and reset button ([captive-portal/](../../captive-portal/)) |
| `nexus-web-panel` | all | Command panel on port 8080 ([web-panel/](../../web-panel/)) |
| `nexus-web-terminal` | arm64 | ttyd browser terminal on port 7681 ([web-terminal/](../../web-terminal/)), with the pinned upstream ttyd |
| `nexus-archive-keyring` | all | Repository signing key + `/etc/apt/sources.list.d/nexus.sources` |

All five come from one source package and share one version, the one in
`debian/changelog`. `nexus` pins the other components to exactly that version,
so a board never runs a mix that was not released together.

## Layout

```
github.com/tridexdarts/nexus        source (this repository); CI builds on every push
github.com/tridexdarts/nexus-apt    apt repository, served by Pages at
                                    https://tridexdarts.github.io/nexus-apt/
  dists/trixie/{InRelease,Release,Release.gpg}
  dists/trixie/{main,contrib}/binary-arm64/Packages(.gz)
  pool/trixie/{main,contrib}/<package>/<package>_<version>_<arch>.deb
  nexus-archive-keyring.deb         newest keyring package, for first-time setup
  nexus-archive-keyring.asc         public key
  index.html                        setup instructions
```

The index is built with `apt-ftparchive` by [publish.sh](publish.sh). Every
version stays in the pool, so `apt install nexus=0.1.0` can roll a board back.
To prune, delete files from `pool/` in nexus-apt and run `publish.sh` with no
`.deb` arguments.

The components follow Debian's archive areas, and each package's `Section`
in [debian/control](../../debian/control) decides where it goes. Everything
is free software (GPL-3+). `nexus-web-panel` runs the proprietary Autodarts
client, so it is in **contrib**, and the `nexus` metapackage depends on it,
so it is in contrib as well. The other packages are in **main**.

## One-time setup

### 1. Signing key

Generate it on a trusted machine, in a throwaway keyring:

```bash
export GNUPGHOME=$(mktemp -d)
gpg --batch --passphrase '' --quick-gen-key 'Tridex Nexus Archive Signing Key' ed25519 sign never
gpg --armor --export                > packaging/apt/nexus-archive-keyring.asc   # commit this
gpg --armor --export-secret-keys    > nexus-apt-signing.secret.asc              # never commit this
```

- Put the contents of `nexus-apt-signing.secret.asc` into the nexus
  repository secret **`APT_SIGNING_KEY`** (Settings → Secrets and variables →
  Actions). If you gave the key a passphrase, add it as `APT_SIGNING_PASSPHRASE`.
- Keep an offline copy of the secret key (password manager), then delete the
  file and `$GNUPGHOME`. Lose the key and every board needs a manually
  installed new keyring package.
- `never` expires: an expired key silently stops all board updates. To rotate,
  ship the new key in a `nexus-archive-keyring` release *while the old one
  still signs*, then switch.

### 2. apt repository

1. Create the **public** repository `tridexdarts/nexus-apt` with an initial commit
   (e.g. a README; the workflow cannot check out an empty repository).
2. Settings → Pages → *Deploy from a branch*, `main`, `/ (root)`.

If the name or owner differs, change `APT_REPO` in
[.github/workflows/packages.yml](../../.github/workflows/packages.yml) and the
URL in [nexus.sources](nexus.sources) and [index.html](index.html).

### 3. Deploy key

The workflow pushes to nexus-apt with an SSH key that can write to that one
repository only:

```bash
ssh-keygen -t ed25519 -N '' -C nexus-apt-deploy -f nexus-apt-deploy
```

- `nexus-apt-deploy.pub` → nexus-apt: Settings → Deploy keys, **Allow write access**.
- `nexus-apt-deploy` → nexus: secret **`APT_REPO_DEPLOY_KEY`**.

Then delete both files.

## Setting up a board

```bash
curl -fsSLO https://tridexdarts.github.io/nexus-apt/nexus-archive-keyring.deb
sudo apt install ./nexus-archive-keyring.deb
sudo apt update
sudo apt install nexus
```

Do this over Ethernet: `nexus-captive-portal` hands wlan0 from ifupdown to
NetworkManager on first install, which drops an SSH session running over Wi-Fi.

Automatic updates via `unattended-upgrades`:

```bash
sudo apt install unattended-upgrades
echo 'Unattended-Upgrade::Origins-Pattern:: "origin=Tridex,label=Tridex Nexus";' \
  | sudo tee /etc/apt/apt.conf.d/51nexus-unattended-upgrades
```

## Building locally

```bash
sudo apt install build-essential devscripts equivs
sudo mk-build-deps -i -r debian/control
dpkg-buildpackage -us -uc -b          # .debs land in the parent directory
```

Add `--host-arch=arm64 -d` on an x86 machine: `nexus-web-terminal` is the one
arm64 package, but it only carries the downloaded ttyd, so no cross compiler
is needed. Building needs network access (ttyd download, checked against the
SHA-256 in `debian/rules`) and `packaging/apt/nexus-archive-keyring.asc`
(step 1 above).

### Updating ttyd

ttyd is not in Debian trixie, so `debian/rules` downloads the upstream static
build `ttyd.aarch64`, pinned by `TTYD_VERSION` and `TTYD_SHA256`. To update,
take both from the release's `SHA256SUMS`, add a changelog entry and release.
Once the boards run a Debian release that has ttyd (forky has it), replace the
download with `Depends: ttyd`.

To try an unreleased build on a board, copy the `.deb`s over and
`sudo apt install ./*.deb`. CI builds without a tag get a snapshot version,
so they never pass for a release: `0.2.0~git<date>.<commit>` while the top
changelog entry is `UNRELEASED` (sorts before 0.2.0), otherwise
`0.1.0+git<date>.<commit>` (after 0.1.0, before the next release). A board
moves on to the real release with the next `apt upgrade`.

## What the captive-portal package does to the system

`captive-portal/install.sh` used to do this by hand; the maintainer scripts in
[debian/](../../debian/) now do it on install and upgrade:

- **`/etc/comitup.conf`**: comitup owns that file, so `preinst` diverts
  comitup's copy to `/etc/comitup.conf.distrib` (`dpkg-divert`), and the
  package installs `/etc/comitup.conf` as a link to
  `/usr/share/nexus/comitup.conf`. Config changes go through a release;
  edits on the board are overwritten. Removing the package restores comitup's
  own file.
- **comitup-web**: a packaged drop-in
  (`/usr/lib/systemd/system/comitup-web.service.d/nexus-portal.conf`) makes
  it run the Nexus portal as the system user `nexus-portal` (created via
  sysusers). Upgrades from 0.1.0 remove the old generated drop-in
  `/etc/systemd/system/comitup-web.service.d/nexus-templates.conf`.
- **Units**: enables `nexus-initpw.socket` (password helper) and
  `nexus-wifi-button.service` (LED, reset button). `nexus-access-reset.service`
  is installed but never enabled or started by the package scripts.
- **`/etc/network/interfaces`**: a wlan0 stanza is commented out (backup
  alongside) on every install or upgrade that finds one — normally only the
  first, unless `dietpi-config` put it back.
- **DietPi**: removes the Wi-Fi blacklist and disables `dietpi-wifi-monitor`.
- **Restarts**: comitup only when `comitup.conf` changed; NetworkManager only
  when the interfaces file was changed; comitup-web (if the hotspot is up)
  and nexus-wifi-button on every upgrade.
- **Leftovers** of `install.sh` (`/usr/local/sbin/nexus-comitup-callback`,
  `/etc/nexus/comitup-templates`) are removed.

## Boards set up with the old install.sh scripts

The packages take over cleanly: `nexus-web-panel` and `nexus-web-terminal`
stop and remove the units the scripts put in `/etc/systemd/system` (they would
shadow the packaged ones) and delete the copies in `/usr/local`. An existing
`/etc/nexus/actions.json` is kept. The package only creates it when missing
and never changes it later, so new default buttons in a release do not reach
boards that already have the file. (It is deliberately not a conffile: dpkg
would stop and ask about a locally edited one, and an upgrade run from the
panel or by unattended-upgrades has no terminal to answer.)
