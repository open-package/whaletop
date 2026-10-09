"""Containers tab: compose projects as expandable groups, standalone containers as plain rows."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.binding import Binding

from .. import format as fmt
from ..docker_client import ComposeProject, container_name, group_compose
from ..screens.cleanup import CleanupOption
from ..stats import Sample
from ..widgets.resource_table import Column, ResourceView, Row

ACTIVE = ("running", "paused", "restarting")


def _blank_stats(text: str = "-") -> tuple[dict[str, Any], dict[str, Any]]:
    blank = Text(text, style="dim")
    return ({"cpu": blank, "mem": blank, "mempct": blank, "net": blank, "blk": blank, "pids": blank},
            {"cpu": -1.0, "mem": -1, "mempct": -1.0, "net": -1.0, "blk": -1.0, "pids": -1})


def _stats_cells(cpu, mem, limit, rx, tx, br, bw, pids) -> tuple[dict[str, Any], dict[str, Any]]:
    mem_pct = mem / limit * 100 if limit else 0.0
    cells = {
        "cpu": fmt.mini_bar(cpu),
        "mem": f"{fmt.human_size(mem)} / {fmt.human_size(limit)}",
        "mempct": fmt.mini_bar(mem_pct),
        "net": f"↓{fmt.human_size(rx)} ↑{fmt.human_size(tx)}",
        "blk": f"r{fmt.human_size(br)} w{fmt.human_size(bw)}",
        "pids": str(pids),
    }
    return cells, {"cpu": cpu, "mem": mem, "mempct": mem_pct, "net": rx + tx, "blk": br + bw, "pids": pids}


def stat_cells(c: dict[str, Any], s: Sample | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Live-stat cells and their sort values for one container summary."""
    if c.get("State") != "running":
        return _blank_stats()
    if s is None:
        return _blank_stats("…")
    return _stats_cells(s.cpu, s.mem, s.mem_limit, s.net_rx_rate, s.net_tx_rate,
                        s.blk_r_rate, s.blk_w_rate, s.pids)


def project_stat_cells(p: ComposeProject, stats: dict[str, Sample]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Stats summed over a compose project's running containers."""
    ss = [stats[c["Id"]] for c in p.containers if c.get("State") == "running" and c["Id"] in stats]
    if not ss:
        return _blank_stats()
    return _stats_cells(sum(s.cpu for s in ss), sum(s.mem for s in ss), max(s.mem_limit for s in ss),
                        sum(s.net_rx_rate for s in ss), sum(s.net_tx_rate for s in ss),
                        sum(s.blk_r_rate for s in ss), sum(s.blk_w_rate for s in ss), sum(s.pids for s in ss))


def status_text(c: dict[str, Any]) -> Text:
    return Text(c.get("Status", ""), style=fmt.STATE_STYLE.get(c.get("State", ""), ""))


class ContainersView(ResourceView):
    COLUMNS = [
        Column("dot", " ", 1),
        Column("name", "NAME"),
        Column("image", "IMAGE"),
        Column("status", "STATUS"),
        Column("cpu", "CPU%", 12),
        Column("mempct", "MEM%", 12),
        Column("mem", "MEM / LIMIT"),
        Column("net", "NET ↓↑/s"),
        Column("blk", "DISK r/w/s"),
        Column("pids", "PIDS"),
        Column("host_ports", "HOST PORT"),
        Column("ctr_ports", "CONTAINER PORT"),
    ]
    SORT = "name"
    NOUN = "containers"
    KIND = "container"
    BINDINGS = [
        Binding("enter,space", "toggle_expand", "Expand", show=False),
        Binding("s", "start_stop", "Start/Stop"),
        Binding("r", "restart", "Restart"),
        Binding("p", "pause", "Pause", show=False),
        Binding("k,f9", "kill", "Kill", show=False),
        Binding("d,delete", "remove", "Remove"),
        Binding("l", "logs", "Logs"),
        Binding("e", "exec", "Shell"),
        Binding("a", "attach", "Attach", show=False),
        Binding("i", "inspect", "Inspect"),
        Binding("u", "up", "Up"),
        Binding("D", "down", "Down", show=False),
        Binding("P", "pull", "Pull", show=False),
        Binding("h", "toggle_all", "Hide stopped"),
    ]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.show_all = True
        self.collapsed: set[str] = set()  # projects start expanded
        self.table.tree_col = "name"

    def fetch(self) -> list[dict[str, Any]]:
        return self.dapp.svc.containers()

    def _apply(self, data: Any) -> None:
        self.dapp.containers_loaded(data)
        super()._apply(data)

    # --- rows -----------------------------------------------------------------
    def _container_row(self, c: dict[str, Any], stats: dict[str, Sample],
                       project: ComposeProject | None) -> Row:
        state = c.get("State", "")
        cells, sort = stat_cells(c, stats.get(c["Id"]))
        image = c.get("Image", "")
        if image.startswith("sha256:"):
            image = fmt.short_id(image)
        cells.update({
            "dot": fmt.state_dot(state),
            "name": container_name(c),
            "image": image,
            "status": status_text(c),
        })
        cells["host_ports"], cells["ctr_ports"] = fmt.ports_split(c.get("Ports"))
        sort["dot"] = (state != "running", -c.get("Created", 0))
        sort["status"] = (state != "running", c.get("Status", ""))
        return Row(c["Id"], cells, sort, parent=f"p:{project.name}" if project else None,
                   data={"kind": "container", "container": c, "project": project})

    def _keep(self, c: dict[str, Any]) -> bool:
        return self.show_all or c.get("State") in ACTIVE

    def build_rows(self, data: list[dict[str, Any]]) -> list[Row]:
        stats = self.dapp.stats.snapshot()
        projects = group_compose(data)
        in_project = {c["Id"] for p in projects for c in p.containers}
        rows: list[Row] = []
        for p in projects:
            kids = [c for c in p.containers if self._keep(c)]
            if not kids:
                continue
            open_ = p.name not in self.collapsed
            total = len(p.containers)
            style = "green" if p.running == total else "yellow" if p.running else "red"
            n_svc = len(p.services)
            cells, sort = project_stat_cells(p, stats)
            cells.update({
                "dot": Text("◆", style=style),
                "name": Text.assemble(("▾ " if open_ else "▸ ", "bold"), (p.name, "bold")),
                "image": Text(f"compose · {n_svc} service{'s' if n_svc != 1 else ''}", style="dim"),
                "status": Text(f"{p.running}/{total} running", style=style),
                "host_ports": "",
                "ctr_ports": "",
            })
            sort.update(dot=(p.running == 0, 0), status=(p.running == 0, ""), name=p.name.lower())
            rows.append(Row(f"p:{p.name}", cells, sort, data={"kind": "project", "project": p, "container": None}))
            if open_:
                rows.extend(self._container_row(c, stats, p) for c in kids)
        rows.extend(self._container_row(c, stats, None) for c in data
                    if c["Id"] not in in_project and self._keep(c))
        return rows

    def status_count(self) -> str:
        data = self.data or []
        n_proj = len(group_compose(data))
        s = f"{len(data)} containers"
        if n_proj:
            s += f" · {n_proj} compose project{'s' if n_proj != 1 else ''}"
        return s

    def status_extra(self) -> str:
        return "" if self.show_all else "hiding stopped (h)"

    # --- selection --------------------------------------------------------------
    def _sel(self) -> dict[str, Any] | None:
        row = self.selected
        return row.data if row else None

    def _is_project_row(self) -> bool:
        d = self._sel()
        return bool(d and d["kind"] == "project")

    def selected_container(self) -> dict[str, Any] | None:
        d = self._sel()
        if d and d["kind"] == "container":
            return d["container"]
        if d:
            self.dapp.notify("Select a container (this is a compose project row)", severity="warning")
        return None

    def selected_project(self) -> ComposeProject | None:
        """The selected project, or the project of the selected container."""
        d = self._sel()
        if d and d["project"] is None:
            self.dapp.notify("Not part of a compose project", severity="warning")
        return d["project"] if d else None

    def _with(self, fn):
        c = self.selected_container()
        if c is not None:
            fn(c, c["Id"], container_name(c))

    # --- expand / filter ----------------------------------------------------
    def action_toggle_expand(self) -> None:
        d = self._sel()
        if not d:
            return
        if d["kind"] == "container":
            return self.action_inspect()
        name = d["project"].name
        self.collapsed ^= {name}
        self.redraw()
        keys = self.table._shown
        if f"p:{name}" in keys:
            self.table.move_cursor(row=keys.index(f"p:{name}"))

    def on_data_table_row_selected(self, ev) -> None:
        ev.stop()
        self.action_toggle_expand()

    def action_toggle_all(self) -> None:
        self.show_all = not self.show_all
        self.redraw()

    # --- compose helpers ----------------------------------------------------------
    def _compose_cmd(self, p: ComposeProject, *args: str, title: str) -> None:
        argv = self.dapp.svc.compose_argv(p, *args)
        self.dapp.show_command(f"{title}  ·  {' '.join(argv)}", argv, cwd=p.working_dir)

    def _need_files(self, p: ComposeProject) -> bool:
        if p.files_exist:
            return True
        self.dapp.notify(f"Compose file(s) for {p.name} not found: {', '.join(p.config_files) or '?'}",
                         severity="error")
        return False

    # --- actions: a project row acts on the whole stack, a container row on itself --
    def action_start_stop(self) -> None:
        if not self._is_project_row():
            return self._with(self._container_start_stop)
        p = self.selected_project()
        verb = "stop" if p.running else "start"
        if p.files_exist:
            return self._compose_cmd(p, verb, title=f"{p.name}: {verb}")
        svc = self.dapp.svc
        if p.running:
            ids = [c["Id"] for c in p.containers if c.get("State") == "running"]
            self.dapp.run_docker(lambda: [svc.stop(i) for i in ids], ok=f"Stopped {p.name}")
        else:
            ids = [c["Id"] for c in p.containers]
            self.dapp.run_docker(lambda: [svc.start(i) for i in ids], ok=f"Started {p.name}")

    def _container_start_stop(self, c, cid, name) -> None:
        svc, state = self.dapp.svc, c.get("State")
        if state == "running":
            self.dapp.run_docker(lambda: svc.stop(cid), ok=f"Stopped {name}")
        elif state == "paused":
            self.dapp.run_docker(lambda: svc.unpause(cid), ok=f"Unpaused {name}")
        else:
            self.dapp.run_docker(lambda: svc.start(cid), ok=f"Started {name}")
        self.dapp.notify(f"{'Stopping' if state == 'running' else 'Starting'} {name}…", timeout=2)

    def action_restart(self) -> None:
        if self._is_project_row():
            p = self.selected_project()
            if p.files_exist:
                return self._compose_cmd(p, "restart", title=f"{p.name}: restart")
            svc, ids = self.dapp.svc, [c["Id"] for c in p.containers]
            return self.dapp.run_docker(lambda: [svc.restart(i) for i in ids], ok=f"Restarted {p.name}")

        def go(c, cid, name):
            self.dapp.notify(f"Restarting {name}…", timeout=2)
            self.dapp.run_docker(lambda: self.dapp.svc.restart(cid), ok=f"Restarted {name}")
        self._with(go)

    def action_pause(self) -> None:
        def go(c, cid, name):
            svc = self.dapp.svc
            if c.get("State") == "paused":
                self.dapp.run_docker(lambda: svc.unpause(cid), ok=f"Unpaused {name}")
            elif c.get("State") == "running":
                self.dapp.run_docker(lambda: svc.pause(cid), ok=f"Paused {name}")
        self._with(go)

    def action_kill(self) -> None:
        def go(c, cid, name):
            if c.get("State") != "running":
                return self.dapp.notify(f"{name} is not running", severity="warning")
            self.dapp.confirm(f"Kill {name}?", "Sends SIGKILL immediately.",
                              lambda _: self.dapp.run_docker(lambda: self.dapp.svc.kill(cid), ok=f"Killed {name}"))
        self._with(go)

    def action_remove(self) -> None:
        if self._is_project_row():
            return self.action_down()

        def go(c, cid, name):
            running = c.get("State") in ACTIVE
            self.dapp.confirm(
                f"Remove container {name}?",
                "It is running and will be force-removed." if running else "",
                lambda _: self.dapp.run_docker(lambda: self.dapp.svc.remove_container(cid, force=running),
                                               ok=f"Removed {name}"),
                label="Force remove" if running else "Remove")
        self._with(go)

    def action_logs(self) -> None:
        if not self._is_project_row():
            return self._with(lambda c, cid, name: self.dapp.show_container_logs(cid, name))
        p = self.selected_project()
        if not p.files_exist:
            return self.dapp.notify("Compose file not found; open logs per container instead",
                                    severity="warning")
        argv = self.dapp.svc.compose_argv(p, "logs", "-f", "--tail", "200")
        self.dapp.show_command(f"{p.name}: logs", argv, cwd=p.working_dir, timestamps_flag="-t")

    def action_exec(self) -> None:
        def go(c, cid, name):
            if c.get("State") != "running":
                return self.dapp.notify(f"{name} is not running", severity="warning")
            self.dapp.exec_shell(cid, name)
        self._with(go)

    def action_attach(self) -> None:
        def go(c, cid, name):
            if c.get("State") != "running":
                return self.dapp.notify(f"{name} is not running", severity="warning")
            self.dapp.attach(cid, name)
        self._with(go)

    def action_inspect(self) -> None:
        self._with(lambda c, cid, name: self.dapp.show_inspect("container", cid, name))

    def action_up(self) -> None:
        p = self.selected_project()
        if p and self._need_files(p):
            self._compose_cmd(p, "up", "-d", "--remove-orphans", title=f"{p.name}: up")

    def action_pull(self) -> None:
        p = self.selected_project()
        if p and self._need_files(p):
            self._compose_cmd(p, "pull", title=f"{p.name}: pull")

    def action_down(self) -> None:
        p = self.selected_project()
        if not p:
            return
        if p.files_exist:
            self.dapp.confirm(f"compose down {p.name}?", "Stops and removes all containers and networks "
                              "of the project. Volumes are kept.",
                              lambda _: self._compose_cmd(p, "down", title=f"{p.name}: down"), label="Down")
        else:
            ids = [c["Id"] for c in p.containers]
            self.dapp.confirm(f"Remove all {len(ids)} containers of {p.name}?",
                              "Compose file not found, so containers are force-removed directly.",
                              lambda _: self.dapp.run_docker(
                                  lambda: [self.dapp.svc.remove_container(i, force=True) for i in ids],
                                  ok=f"Removed {p.name}"))

    # --- clean up -------------------------------------------------------------------
    def cleanup_options(self) -> list[CleanupOption]:
        stopped = [c for c in self.data if c.get("State") in ("exited", "created", "dead")]
        df = self.dapp.meters.df
        sizes = {x["Id"]: x.get("SizeRw") or 0 for x in (df or {}).get("Containers") or []}
        in_compose = [c for c in stopped if (c.get("Labels") or {}).get("com.docker.compose.project")]
        return [CleanupOption(
            "stopped", "Remove all stopped containers", [container_name(c) for c in stopped],
            sum(sizes.get(c["Id"], 0) for c in stopped) if df else None, noun="stopped containers",
            note=(f"{len(in_compose)} belong to compose projects (e.g. finished one-off jobs); "
                  "compose recreates them on the next up." if in_compose else ""))]

    def run_cleanup(self, option_id: str) -> None:
        self.dapp.run_docker(lambda: self.dapp.svc.prune_containers(),
                             ok=lambda r: f"Removed {len(r.get('ContainersDeleted') or [])} containers, "
                                          f"reclaimed {fmt.human_size(r.get('SpaceReclaimed', 0))}",
                             kinds=("container",), refresh_df=True)
