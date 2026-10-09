# Installation

## Requirements

| Requirement | Details |
|---|---|
| Python | 3.10 or later |
| Docker Engine | Any supported version. The client negotiates the API version with the daemon. |
| Docker socket access | Membership of the `docker` group, root, or a remote connection (see [Remote hosts](#remote-hosts)) |
| `docker` CLI | Required for interactive shells, `attach` and Compose operations |
| Docker Compose v2 | Required for Compose operations (`docker compose`). The legacy `docker-compose` v1 is not supported. |
| Terminal | Any terminal emulator with 256 colours and Unicode; 100 columns or wider is recommended |

To grant the current user access to the local socket:

```sh
sudo usermod -aG docker "$USER"   # takes effect at the next login
```

## Debian and Ubuntu

whaletop is published in a signed apt repository. Supported releases are Ubuntu 22.04 and later
and Debian 12 and later.

```sh
curl -fsSL https://open-package.github.io/whaletop/whaletop.gpg \
  | sudo tee /usr/share/keyrings/whaletop.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/whaletop.gpg] https://open-package.github.io/whaletop stable main" \
  | sudo tee /etc/apt/sources.list.d/whaletop.list
sudo apt update && sudo apt install whaletop
```

The package bundles its Python dependencies under `/usr/lib/whaletop` and does not conflict with
Python packages installed by the distribution. It recommends, but does not require, the Docker
CLI (`docker-ce-cli` or `docker.io`) and the Compose plugin.

**Upgrade:**

```sh
sudo apt update && sudo apt upgrade
```

**Remove:**

```sh
sudo apt remove whaletop
sudo rm /etc/apt/sources.list.d/whaletop.list /usr/share/keyrings/whaletop.gpg
```

## PyPI

For other Linux distributions and macOS.

=== "pipx"

    ```sh
    pipx install whaletop
    pipx upgrade whaletop      # upgrade
    pipx uninstall whaletop    # remove
    ```

=== "uv"

    ```sh
    uv tool install whaletop
    uv tool upgrade whaletop   # upgrade
    uv tool uninstall whaletop # remove
    ```

=== "pip"

    ```sh
    python3 -m pip install --user whaletop
    ```

## From source

```sh
git clone https://github.com/open-package/whaletop.git
cd whaletop
pipx install .
```

For development, see [Development](releasing.md#development).

## Remote hosts

whaletop selects the Docker daemon in this order:

1. The `-H` / `--host` option.
2. The `DOCKER_HOST` environment variable, together with `DOCKER_TLS_VERIFY` and
   `DOCKER_CERT_PATH`.
3. The current Docker CLI context (`docker context use …`), including its TLS settings.
4. The default local socket.

### SSH

```sh
whaletop -H ssh://user@server
whaletop -H ssh://user@server:2222
DOCKER_HOST=ssh://user@server whaletop
```

whaletop uses the system OpenSSH client and forwards the remote Docker socket to a temporary
local socket over a single connection. This has the following implications:

- `~/.ssh/config`, SSH agents, jump hosts and host aliases apply, as with `ssh`.
- Password and host-key prompts appear in the terminal before the interface starts.
- Interactive shells and Compose operations reuse the same connection.
- The SSH server must permit forwarding. If `sshd_config` sets `AllowTcpForwarding no` or
  `AllowStreamLocalForwarding no`, the connection is refused with an explanatory message.
- The remote user requires access to the Docker socket on the server.

The remote socket defaults to `/var/run/docker.sock`. A different socket, for example for
rootless Docker, can be given as the URL path:

```sh
whaletop -H ssh://user@server/run/user/1000/docker.sock
```

### TCP with TLS

Use the standard Docker environment variables:

```sh
export DOCKER_HOST=tcp://docker.example.com:2376
export DOCKER_TLS_VERIFY=1
export DOCKER_CERT_PATH=~/.docker/certs/example
whaletop
```

A Docker context created with `docker context create --docker "host=…,ca=…,cert=…,key=…"` is
also supported.

!!! warning
    An unencrypted TCP endpoint (`tcp://host:2375`) gives full control of the host to anyone who
    can reach it. Prefer SSH or TLS.

### Docker Desktop, Colima and OrbStack

These products register a Docker CLI context. whaletop uses the current context automatically,
so no configuration is required.

## Verifying the installation

```sh
whaletop --version
```
