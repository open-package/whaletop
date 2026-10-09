# whaletop

An htop-style terminal UI for Docker (unofficial; not affiliated with Docker, Inc.). It covers what Docker Desktop does (containers, compose stacks, images, volumes and networks) without leaving the terminal.

```
CPU[|||||||||||          13.6% of 8 cpu]   Containers: 8 running, 3 exited   Images: 602
Mem[|||                      263M/7.6G]   Disk: images 139G (90G reclaimable) · volumes 2.1G …
Hst ▁▁▂▂▁▃▅▇▅▃▂▁                          Engine: 29.8.0  my-host
 1 Containers  2 Images  3 Volumes  4 Networks
   NAME            IMAGE          STATUS               CPU% ▼        MEM%      MEM / LIMIT   NET ↓↑/s …
 ● busy-loop       alpine         Up 11 minutes        104.0 ▮▮▮▮▮▮  0.0 ····  372K / 7.6G   ↓0B ↑0B
 ● api-1           api:dev        Up 25 minutes (h…)     0.2 ······  0.4 ····  31.9M / 7.6G  ↓262B ↑131B
```

## Install

**Debian / Ubuntu** (Ubuntu 22.04+, Debian 12+):

```sh
curl -fsSL https://open-package.github.io/whaletop/whaletop.gpg | sudo tee /usr/share/keyrings/whaletop.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/whaletop.gpg] https://open-package.github.io/whaletop stable main" \
  | sudo tee /etc/apt/sources.list.d/whaletop.list
sudo apt update && sudo apt install whaletop
```

**From source**, any OS with Python 3.10+:

```sh
pipx install .                # or: python -m venv .venv && .venv/bin/pip install -e .
whaletop                      # or: python -m whaletop
whaletop -H ssh://me@server   # any DOCKER_HOST-style address
```

whaletop requires Python 3.10+ and access to the Docker socket. It also needs the `docker` CLI for exec, attach and compose. It connects to `--host`, then `$DOCKER_HOST`, then the docker CLI's current context, so Docker Desktop's `desktop-linux` socket works without extra setup.

## What you can do

| Tab | Shows | Keys |
|---|---|---|
| **1 Containers** | Compose projects as expandable ◆ groups (with summed CPU and memory), their containers nested below, and standalone containers as plain rows. Live CPU%, MEM%, mem/limit, net and disk I/O rates, PIDs, ports | `enter` expand/collapse · `s` start/stop · `r` restart · `l` logs · `d` remove (on a project row these act on the whole stack, and `d` runs `compose down`) · `p` pause · `k`/`F9` kill · `e` shell · `a` attach · `i` inspect · `u` compose up · `D` down · `P` pull · `h` hide stopped · `X` clean up stopped containers |
| **2 Images** | repo, tag, size, age, containers using each image | `P` pull · `R` run · `d` remove · `X` clean up: dangling images, all unused images, build cache |
| **3 Volumes** | driver, which containers use it, size | `d` remove · `X` clean up: unused anonymous / all unused volumes |
| **4 Networks** | driver, subnet, attached containers | `d` remove · `X` clean up unused networks |

The following keys work on every list:
- `/` (or `F3`/`F4`) filters.
- `>`/`F6` and `<` cycle the sort column. Clicking a column header also sorts.
- `I` inverts the sort order.
- `1`–`4`, `[` and `]` switch tabs.
- `F5` refreshes.
- `?`/`F1` opens help.
- `q`/`F10` quits.

In the logs viewer, `/` filters lines, `f` toggles follow, `t` toggles timestamps, `g`/`G` jump to the top/bottom, and `esc` goes back.

Destructive actions always ask for confirmation. `X` opens a clean-up dialog that lists exactly what each option would remove and how much space it frees before anything is deleted. Exec and attach suspend the TUI, hand your terminal to `docker exec -it` or `docker attach`, and bring whaletop back when you exit.

## How it works

- **Live stats:** one streaming `/containers/{id}/stats` connection per running container, each on its own background thread (`stats.py`). CPU% uses the same formula as `docker stats`. Memory excludes the page cache.
- **Updates:** a `/events` subscription (`events.py`) marks the affected tabs as stale, and they reload within 300 ms. A 5-second poll on the container list catches anything the event stream missed.
- **No UI blocking:** every Docker API call runs on a daemon thread, so slow calls never freeze the UI or delay quitting. `/system/df` can take 30s or more on hosts with hundreds of images. That's why the Disk line can show *calculating…* for a while after start; it refreshes every 2 minutes.
- **Compose:** projects come from `com.docker.compose.*` labels. Project actions run `docker compose -p <project> --project-directory <dir> -f <files> …`. If the compose files no longer exist, stop, restart and remove still work by acting on the containers directly.

## Development

```sh
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest           # unit + Textual pilot tests against a fake Docker service
```

Releasing and packaging: see [packaging/README.md](packaging/README.md).

Layout: `src/whaletop/app.py` (app shell), `views/` (one class per tab), `widgets/resource_table.py` (sortable/filterable table base), `widgets/meters.py` (header), `screens/` (logs, inspect, dialogs, help), `docker_client.py` (the only module that talks to Docker).

## License

Apache License 2.0. See [LICENSE](LICENSE).

whaletop is an independent project. Docker is a trademark of Docker, Inc., and whaletop is not affiliated with or endorsed by Docker, Inc.
