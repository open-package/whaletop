# whaletop

[![PyPI](https://img.shields.io/pypi/v/whaletop)](https://pypi.org/project/whaletop/)
[![Python](https://img.shields.io/pypi/pyversions/whaletop)](https://pypi.org/project/whaletop/)
[![CI](https://github.com/open-package/whaletop/actions/workflows/ci.yml/badge.svg)](https://github.com/open-package/whaletop/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/open-package/whaletop/blob/main/LICENSE)

A terminal user interface for Docker in the style of `htop`. whaletop provides the container,
Compose, image, volume and network management of Docker Desktop in a keyboard-driven console
application that runs locally, over SSH and on headless servers.

**Documentation:** <https://open-package.github.io/whaletop/>

![whaletop containers view](https://raw.githubusercontent.com/open-package/whaletop/main/docs/assets/containers.png)

## Features

- **Live resource usage.** CPU, memory, network and block I/O per container, aggregated per
  Compose project, with host-level meters and CPU history.
- **Compose-aware.** Containers are grouped by Compose project; start, stop, restart, pull,
  `up` and `down` apply to a whole stack or a single service.
- **Container operations.** Logs with filtering and follow mode, interactive shell (`exec`),
  `attach`, inspect, pause, kill and remove.
- **Images, volumes and networks.** Usage by container, size, pull, run and remove.
- **Previewed clean-up.** Each prune operation lists the affected objects and the reclaimable
  space before anything is removed.
- **Event-driven.** Views update from the Docker event stream; no manual refresh is required.

## Installation

### Debian and Ubuntu

Supported releases: Ubuntu 22.04 and later, Debian 12 and later.

```sh
curl -fsSL https://open-package.github.io/whaletop/whaletop.gpg \
  | sudo tee /usr/share/keyrings/whaletop.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/whaletop.gpg] https://open-package.github.io/whaletop stable main" \
  | sudo tee /etc/apt/sources.list.d/whaletop.list
sudo apt update && sudo apt install whaletop
```

### PyPI

For other Linux distributions and macOS. Requires Python 3.10 or later.

```sh
pipx install whaletop
# or
uv tool install whaletop
```

See the [installation guide](https://open-package.github.io/whaletop/install/) for source
installs, upgrades and removal.

## Usage

```sh
whaletop                         # local Docker daemon
whaletop -H ssh://user@server    # remote daemon over SSH
```

The daemon is selected from `--host`, then `DOCKER_HOST` (including `DOCKER_TLS_VERIFY` and
`DOCKER_CERT_PATH`), then the current Docker CLI context. See
[remote hosts](https://open-package.github.io/whaletop/install/#remote-hosts) for SSH and TLS
details.

| Key | Action |
|---|---|
| `1`–`4` | Containers, Images, Volumes, Networks |
| `/` | Filter the current list |
| `>` / `<` | Change the sort column |
| `s` `r` `d` | Start/stop, restart, remove |
| `l` `e` `i` | Logs, shell, inspect |
| `u` `D` | Compose up, Compose down |
| `X` | Clean up unused objects |
| `?` | Help |
| `q` | Quit |

The full key reference is in the [usage guide](https://open-package.github.io/whaletop/usage/).

## Requirements

- Access to a Docker Engine API (local socket, SSH or TCP). Membership of the `docker` group
  or equivalent permissions is required for the local socket.
- The `docker` CLI, for interactive shells, `attach` and Compose operations.
- Docker Compose v2 (`docker compose`), for Compose operations.

## Development

```sh
git clone https://github.com/open-package/whaletop.git
cd whaletop
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

Release and packaging procedures are documented in the
[maintainer guide](https://open-package.github.io/whaletop/releasing/).

## License

Licensed under the [Apache License 2.0](https://github.com/open-package/whaletop/blob/main/LICENSE).

whaletop is an independent project and is not affiliated with or endorsed by Docker, Inc.
Docker is a trademark of Docker, Inc.
