#!/bin/sh
# Add .deb files to the Nexus apt repository and re-sign its index.
#
#   packaging/apt/publish.sh <repo-dir> <file.deb>...
#
# <repo-dir> is a checkout of the apt repository (served by GitHub Pages).
# Every version stays in the pool, so "apt install nexus=<old version>" works;
# to drop one, delete its file from pool/ and run this script without debs.
# Each package goes to the component its Section names, as in Debian:
# "contrib/net" -> contrib, "net" -> main.
#
# Environment:
#   SUITE           distribution codename (default: trixie)
#   ARCHITECTURES   index architectures (default: arm64)
#   GPG_KEY_ID      key to sign with (default: gpg's default key)
#   GPG_PASSPHRASE  passphrase for that key, if it has one
set -eu

[ $# -ge 1 ] || { sed -n '2,15s/^# \{0,1\}//p' "$0" >&2; exit 2; }
REPO=$(cd "$1" && pwd); shift
SUITE=${SUITE:-trixie}
ARCHITECTURES=${ARCHITECTURES:-arm64}
COMPONENTS="main contrib"
HERE=$(cd "$(dirname "$0")" && pwd)

for deb in "$@"; do
    pkg=$(dpkg-deb -f "$deb" Package)
    case $(dpkg-deb -f "$deb" Section) in
        contrib/*) component=contrib ;;
        */*)       echo "error: $(basename "$deb"): component not in COMPONENTS ($COMPONENTS)" >&2; exit 1 ;;
        *)         component=main ;;
    esac
    dest="$REPO/pool/$SUITE/$component/$pkg/$(basename "$deb")"
    if [ -e "$dest" ]; then
        # A published version must never change: clients would see a hash mismatch.
        if cmp -s "$deb" "$dest"; then
            echo "unchanged: $(basename "$deb")"; continue
        fi
        echo "error: $(basename "$deb") is already published with different content; bump the version" >&2
        exit 1
    fi
    mkdir -p "$(dirname "$dest")"
    cp "$deb" "$dest"
    echo "added:     $(basename "$deb")"
done

cd "$REPO"
dist=dists/$SUITE
rm -f "$dist/Release" "$dist/InRelease" "$dist/Release.gpg"
for component in $COMPONENTS; do
    # An empty component still gets (empty) indices, so apt finds them.
    mkdir -p "pool/$SUITE/$component"
    for arch in $ARCHITECTURES; do
        dir=$dist/$component/binary-$arch
        mkdir -p "$dir"
        # Paths in Packages are relative to the repo root, hence run from there.
        apt-ftparchive --arch "$arch" packages "pool/$SUITE/$component" > "$dir/Packages"
        gzip -9nkf "$dir/Packages"
    done
done

apt-ftparchive \
    -o APT::FTPArchive::Release::Origin="Tridex" \
    -o APT::FTPArchive::Release::Label="Tridex Nexus" \
    -o APT::FTPArchive::Release::Suite="$SUITE" \
    -o APT::FTPArchive::Release::Codename="$SUITE" \
    -o APT::FTPArchive::Release::Architectures="$ARCHITECTURES" \
    -o APT::FTPArchive::Release::Components="$COMPONENTS" \
    -o APT::FTPArchive::Release::Description="Tridex Nexus board software" \
    release "$dist" > "$dist/Release.new"
mv "$dist/Release.new" "$dist/Release"

set -- --batch --yes
[ -n "${GPG_KEY_ID:-}" ] && set -- "$@" --local-user "$GPG_KEY_ID"
[ -n "${GPG_PASSPHRASE:-}" ] && set -- "$@" --pinentry-mode loopback --passphrase "$GPG_PASSPHRASE"
gpg "$@" --clearsign --output "$dist/InRelease" "$dist/Release"
gpg "$@" --armor --detach-sign --output "$dist/Release.gpg" "$dist/Release"

# Bootstrap files at stable URLs: the key for manual checks, the newest keyring
# package for first-time setup (see index.html).
cp "$HERE/nexus-archive-keyring.asc" nexus-archive-keyring.asc
newest=$(ls pool/"$SUITE"/main/nexus-archive-keyring/*.deb 2>/dev/null | sort -V | tail -n1)
[ -n "$newest" ] && cp "$newest" nexus-archive-keyring.deb
cp "$HERE/index.html" index.html
touch .nojekyll

echo "signed:    $dist/InRelease"
