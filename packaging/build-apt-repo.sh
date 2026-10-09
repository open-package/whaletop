#!/usr/bin/env bash
# Build a signed apt repository from a directory of .deb files.
#
#   packaging/build-apt-repo.sh <debs-dir> <out-dir> <gpg-key-id>
#
# Layout (one suite "stable", one component "main"):
#   <out>/pool/main/w/whaletop/*.deb
#   <out>/dists/stable/{Release,InRelease,Release.gpg}
#   <out>/dists/stable/main/binary-<arch>/Packages{,.gz}
#   <out>/whaletop.gpg   public key (binary, for /usr/share/keyrings)
#   <out>/whaletop.asc   public key (armored)
#
# whaletop is Architecture: all, but the same index is published under every
# common architecture as well, so any apt version finds it.
#
# Requires: apt-ftparchive (apt-utils), gpg with the signing key imported.
set -euo pipefail

DEBS="${1:?usage: $0 <debs-dir> <out-dir> <gpg-key-id>}"
OUT="${2:?usage: $0 <debs-dir> <out-dir> <gpg-key-id>}"
KEY="${3:?usage: $0 <debs-dir> <out-dir> <gpg-key-id>}"
SUITE=stable
COMPONENT=main
ARCHES="all amd64 arm64 armhf i386"

shopt -s nullglob
debs=("$DEBS"/*.deb)
[ ${#debs[@]} -gt 0 ] || { echo "no .deb files in $DEBS" >&2; exit 1; }

rm -rf "$OUT"
mkdir -p "$OUT/pool/$COMPONENT/w/whaletop"
cp "${debs[@]}" "$OUT/pool/$COMPONENT/w/whaletop/"

cd "$OUT"
for arch in $ARCHES; do
    dir="dists/$SUITE/$COMPONENT/binary-$arch"
    mkdir -p "$dir"
    apt-ftparchive packages "pool/$COMPONENT" > "$dir/Packages"
    gzip -9nk "$dir/Packages"
done

apt-ftparchive \
    -o "APT::FTPArchive::Release::Origin=whaletop" \
    -o "APT::FTPArchive::Release::Label=whaletop" \
    -o "APT::FTPArchive::Release::Suite=$SUITE" \
    -o "APT::FTPArchive::Release::Codename=$SUITE" \
    -o "APT::FTPArchive::Release::Architectures=$ARCHES" \
    -o "APT::FTPArchive::Release::Components=$COMPONENT" \
    -o "APT::FTPArchive::Release::Description=whaletop: htop-style terminal UI for Docker" \
    release "dists/$SUITE" > "dists/$SUITE/Release.tmp"
mv "dists/$SUITE/Release.tmp" "dists/$SUITE/Release"

GPG=(gpg --batch --yes --pinentry-mode loopback --local-user "$KEY")
if [ -n "${GPG_PASSPHRASE:-}" ]; then
    GPG+=(--passphrase "$GPG_PASSPHRASE")
fi
"${GPG[@]}" --clearsign -o "dists/$SUITE/InRelease" "dists/$SUITE/Release"
"${GPG[@]}" --armor --detach-sign -o "dists/$SUITE/Release.gpg" "dists/$SUITE/Release"

gpg --batch --yes --export "$KEY" > whaletop.gpg
gpg --batch --yes --armor --export "$KEY" > whaletop.asc

echo "apt repository written to $OUT ($(ls pool/$COMPONENT/w/whaletop | wc -l) package(s))"
