# How it works

## Architecture

whaletop is a [Textual](https://textual.textualize.io/) application. All communication with Docker
goes through a single module, `docker_client.py`, which wraps the Docker SDK for Python and the
`docker` CLI. The views never call Docker directly, which allows the test suite to substitute an
in-memory implementation.

| Module | Responsibility |
|---|---|
| `app.py` | Application shell, tabs, timers and background work |
| `docker_client.py` | Daemon selection, SSH tunnelling, Docker API and CLI calls |
| `stats.py` | Per-container statistics streams |
| `events.py` | Docker event subscription |
| `views/` | One module per tab |
| `widgets/resource_table.py` | Sortable, filterable table with tree rows |
| `widgets/meters.py` | Header meters |
| `screens/` | Log viewer, inspector, dialogs, clean-up and help |

## Live statistics

For every running container, a background thread reads the streaming
`/containers/{id}/stats` endpoint. CPU usage is computed with the same formula as `docker stats`:

```text
cpu % = (Δ container CPU time / Δ system CPU time) × online CPUs × 100
```

Memory usage excludes the inactive page cache (`inactive_file`), as `docker stats` does. Network
and block I/O are reported as rates, derived from consecutive samples. Statistics streams start
and stop as containers start and stop.

## Updates

whaletop subscribes to the daemon's `/events` stream. Each event marks the affected views as
stale, and stale views reload within 300 ms. Container lifecycle events also refresh the "in use"
columns of the image, volume and network views. A container list poll every five seconds covers
events missed during a reconnect.

## Responsiveness

Every Docker API call runs on a background thread, so slow responses never block the interface.
The daemon's disk-usage report (`/system/df`) can take tens of seconds on hosts with many images;
it is refreshed every two minutes and never runs more than once at a time. Background threads do
not delay exit.

## Compose

Compose projects are identified from the `com.docker.compose.*` labels that Docker Compose sets on
every container. Project operations run:

```text
docker compose -p <project> --project-directory <working_dir> -f <config_files> <command>
```

## Remote connections

`ssh://` addresses are handled by the system OpenSSH client rather than the Docker SDK, which
would require additional native libraries. whaletop starts one multiplexed SSH connection that
forwards the remote Docker socket to a private local socket, connects the SDK to that socket and
points `docker` CLI subprocesses at it. The connection is closed when whaletop exits.

## Packaging

The Debian package is `Architecture: all`. Its Python dependencies are pure Python and are
bundled under `/usr/lib/whaletop/vendor`, because the versions distributed by Debian and Ubuntu
are too old. The launcher runs Python in isolated mode with the bundled libraries first on the
import path, so distribution packages cannot interfere.
