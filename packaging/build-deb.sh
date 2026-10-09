#!/usr/bin/env bash
# Build dist/whaletop_<version>_all.deb
#
# The package bundles its Python dependencies (textual, docker, …) under
# /usr/lib/whaletop/vendor because the versions shipped by Debian/Ubuntu are far
# too old. Every dependency is pure Python, so one Architecture: all package
# works on any release with python3 >= 3.10 (Ubuntu 22.04+, Debian 12+).
#
# Usage: MAINTAINER="Your Name <you@example.com>" HOMEPAGE="https://github.com/you/whaletop" \
#          packaging/build-deb.sh
#        MAINTAINER falls back to `git config user.name/user.email`; HOMEPAGE is optional.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' src/whaletop/__init__.py)"
[ -n "$VERSION" ] || { echo "cannot read version from src/whaletop/__init__.py" >&2; exit 1; }

if [ -z "${MAINTAINER:-}" ]; then
    name="$(git config user.name 2>/dev/null || true)"
    email="$(git config user.email 2>/dev/null || true)"
    if [ -n "$name" ] && [ -n "$email" ]; then
        MAINTAINER="$name <$email>"
    else
        echo "Set MAINTAINER=\"Name <email>\" (or git config user.name/user.email)" >&2
        exit 1
    fi
fi

if ! [[ "$MAINTAINER" =~ ^[^\<\>\"]+\ \<[^\<\>@\ ]+@[^\<\>\ ]+\>$ ]]; then
    echo "MAINTAINER must look like: Name <email@example.com>  (got: $MAINTAINER)" >&2
    exit 1
fi

PKG="whaletop_${VERSION}_all"
STAGE="$ROOT/build/deb/$PKG"
LIB="$STAGE/usr/lib/whaletop"
DOC="$STAGE/usr/share/doc/whaletop"
rm -rf "$STAGE"
mkdir -p "$LIB/vendor" "$STAGE/usr/bin" "$DOC" "$STAGE/DEBIAN" "$ROOT/dist"

# --- application + pure-Python dependencies ----------------------------------
cp -r src/whaletop "$LIB/"
"$PYTHON" -m pip install --quiet --disable-pip-version-check --no-compile \
    --target "$LIB/vendor" \
    --only-binary=:all: --implementation py --abi none --platform any --python-version 3.10 \
    "textual>=1.0" "docker>=7.0"
rm -rf "$LIB/vendor/bin"
find "$LIB" -name '__pycache__' -prune -exec rm -rf {} +
if find "$LIB" -name '*.so' | grep -q .; then
    echo "compiled extension found in vendor/; the package would not be Architecture: all" >&2
    exit 1
fi

# --- launcher ------------------------------------------------------------------
# -I: ignore PYTHONPATH and the user's site-packages; the bundled libraries go
# first on sys.path so an old distro python3-textual can never be picked up.
cat > "$STAGE/usr/bin/whaletop" <<'EOF'
#!/usr/bin/python3 -I
import sys

sys.path[:0] = ["/usr/lib/whaletop", "/usr/lib/whaletop/vendor"]

from whaletop.__main__ import main

main()
EOF
chmod 0755 "$STAGE/usr/bin/whaletop"

# --- docs ----------------------------------------------------------------------
cp README.md "$DOC/"
{
    cat <<EOF
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: whaletop
${HOMEPAGE:+Source: $HOMEPAGE
}
Files: *
Copyright: whaletop contributors
License: Apache-2.0

Files: usr/lib/whaletop/vendor/*
Copyright: see the license files in each package's *.dist-info directory
License: various (MIT, BSD-3-Clause, Apache-2.0, MPL-2.0, PSF-2.0)
Comment: Bundled third-party Python libraries; each keeps its own license file.

License: Apache-2.0
EOF
    sed 's/^$/./; s/^/ /' LICENSE
} > "$DOC/copyright"

# --- control files ---------------------------------------------------------------
SIZE_KB="$(du -sk "$STAGE/usr" | cut -f1)"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: whaletop
Version: $VERSION
Architecture: all
Maintainer: $MAINTAINER
Installed-Size: $SIZE_KB
Depends: python3 (>= 3.10)
Recommends: docker-ce-cli | docker.io, docker-compose-plugin | docker-compose-v2
Section: admin
Priority: optional
${HOMEPAGE:+Homepage: $HOMEPAGE
}Description: htop-style terminal UI for Docker
 Manage containers, compose stacks, images, volumes and networks from the
 terminal: live CPU/memory/network stats, logs, exec shells, compose up/down,
 and previewed clean-up of unused resources. Works over SSH and on headless
 servers. Unofficial; not affiliated with Docker, Inc.
EOF

# byte-compile for whichever python3 the target system has, and clean up on removal
cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "configure" ] && command -v python3 >/dev/null 2>&1; then
    python3 -m compileall -q /usr/lib/whaletop >/dev/null 2>&1 || true
fi
EOF
cat > "$STAGE/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
find /usr/lib/whaletop -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
EOF
chmod 0755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm"

(cd "$STAGE" && find usr -type f -exec md5sum {} + > DEBIAN/md5sums)

dpkg-deb --root-owner-group -Zxz --build "$STAGE" "$ROOT/dist/$PKG.deb" >/dev/null
echo "$ROOT/dist/$PKG.deb"
