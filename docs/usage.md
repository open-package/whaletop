# Usage

```sh
whaletop [-H HOST]
```

| Option | Description |
|---|---|
| `-H`, `--host` | Docker daemon address. See [Remote hosts](install.md#remote-hosts). |
| `-V`, `--version` | Print the version and exit. |
| `-h`, `--help` | Print help and exit. |

## Screen layout

The header shows host-level meters: total container CPU and memory against the host's capacity,
a CPU history graph scaled to its recent peak, container counts by state, image count, disk usage
and the engine version.

Below the header are four tabs: **Containers**, **Images**, **Volumes** and **Networks**. The
footer lists the keys available in the current context. A status line above the footer shows the
number of objects, the active filter and the sort column.

## Global keys

| Key | Action |
|---|---|
| `1` `2` `3` `4` | Switch to Containers, Images, Volumes, Networks |
| `]` / `[` | Next / previous tab |
| `F5`, `Ctrl+R` | Refresh all views |
| `?`, `F1` | Help |
| `q`, `F10` | Quit |

## List keys

These keys apply to every tab.

| Key | Action |
|---|---|
| `/`, `F3`, `F4` | Filter. `Enter` keeps the filter, `Esc` clears it. |
| `>`, `F6` / `<` | Next / previous sort column. Clicking a column header also sorts. |
| `I` | Invert the sort order |
| `i` | Inspect the selected object (JSON) |
| `X` | Clean up unused objects (see [Clean-up](#clean-up)) |

## Containers

Containers that belong to a Docker Compose project are grouped under a project row (marked
`◆`), which shows the number of running services and the aggregated CPU, memory, network and
disk usage. Standalone containers appear as plain rows.

The columns are: state, name, image, status, CPU %, memory %, memory usage and limit, network
receive and transmit rate, block read and write rate, process count, host ports and container
ports. Host and container ports are listed in matching order; `-` marks a port that is exposed
but not published.

| Key | On a container row | On a project row |
|---|---|---|
| `Enter`, `Space` | Inspect | Expand or collapse |
| `s` | Start or stop | `docker compose stop` / `start` |
| `r` | Restart | `docker compose restart` |
| `l` | Logs | Combined logs of all services |
| `d`, `Delete` | Remove (confirmation required) | `docker compose down` (confirmation required) |
| `p` | Pause or unpause | – |
| `k`, `F9` | Kill (confirmation required) | – |
| `e` | Open a shell (`bash`, falling back to `sh`) | – |
| `a` | Attach. Detach with `Ctrl+P Ctrl+Q`. | – |
| `u` | `docker compose up -d` for the container's project | `docker compose up -d` |
| `D` | `docker compose down` for the container's project | `docker compose down` |
| `P` | `docker compose pull` for the container's project | `docker compose pull` |
| `h` | Show or hide stopped containers | |

Compose operations run `docker compose` with the project name, working directory and
configuration files recorded in the containers' labels. Their output is shown in a log view. If
the configuration files no longer exist, stop, restart and remove act on the project's containers
directly, and `up` and `pull` are unavailable.

The shell and `attach` suspend the interface and hand the terminal to `docker exec` or
`docker attach`. The interface resumes when the session ends.

## Images

Columns: repository, tag, image ID, size, age and the number of containers using the image.

| Key | Action |
|---|---|
| `P` | Pull an image |
| `R` | Run a new container from the selected image (name, ports and environment) |
| `d`, `Delete` | Remove. An image with several tags is untagged one tag at a time. Images in use require a forced removal. |

## Volumes

Columns: name, driver, containers using the volume, size, creation time and mount point. A volume
that is in use cannot be removed.

## Networks

Columns: name, ID, driver, scope, subnet and connected containers. The built-in `bridge`, `host`
and `none` networks cannot be removed, nor can networks with connected containers.

## Clean-up

`X` opens a dialog that lists, for each option, the objects that would be removed and the space
that would be reclaimed. Nothing is removed until an option is selected; the dialog opens with
**Cancel** focused.

| Tab | Options |
|---|---|
| Containers | All stopped containers |
| Images | Dangling (untagged) images · all images not used by a container · build cache |
| Volumes | Unused anonymous volumes · all unused volumes |
| Networks | Custom networks without containers |

Image sizes are reported as an upper bound, because images share layers. Volume, container and
build-cache sizes come from the daemon's disk-usage report, which can take some time on hosts
with many images; until it is available, sizes are shown as being calculated.

!!! note
    On Docker Engine versions earlier than 23.0, the daemon's volume prune also removes named
    volumes. On those versions whaletop removes the listed anonymous volumes individually, so
    named volumes are never removed by the anonymous option.

## Log viewer

| Key | Action |
|---|---|
| `/` | Show only lines that contain the given text |
| `f` | Toggle follow mode |
| `t` | Toggle timestamps |
| `c` | Clear the view |
| `g` / `G` | Jump to the first / last line |
| `Esc`, `q` | Return to the list |

The viewer keeps the most recent 10,000 lines.
