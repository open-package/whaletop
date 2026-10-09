from __future__ import annotations

from collections import defaultdict

from rich.text import Text
from textual.binding import Binding

from .. import format as fmt
from ..docker_client import container_name
from ..screens.cleanup import CleanupOption
from ..widgets.resource_table import Column, ResourceView, Row


class VolumesView(ResourceView):
    COLUMNS = [
        Column("name", "NAME"),
        Column("driver", "DRIVER"),
        Column("used", "IN USE BY"),
        Column("size", "SIZE"),
        Column("created", "CREATED"),
        Column("mount", "MOUNTPOINT"),
    ]
    SORT = "name"
    NOUN = "volumes"
    KIND = "volume"
    BINDINGS = [
        Binding("d,delete", "remove", "Remove"),
        Binding("i", "inspect", "Inspect"),
    ]

    def fetch(self) -> tuple[list, list]:
        svc = self.dapp.svc
        return svc.volumes(), svc.containers()

    def build_rows(self, data) -> list[Row]:
        volumes, containers = data
        users: dict[str, list[str]] = defaultdict(list)
        for c in containers:
            for m in c.get("Mounts") or []:
                if m.get("Type") == "volume" and m.get("Name"):
                    users[m["Name"]].append(container_name(c))
        sizes = {}
        df = self.dapp.meters.df
        if df:
            sizes = {v["Name"]: (v.get("UsageData") or {}).get("Size", -1) for v in df.get("Volumes") or []}
        rows = []
        for v in volumes:
            name = v["Name"]
            u = users.get(name, [])
            size = sizes.get(name)
            cells = {
                "name": name if len(name) < 40 else name[:12] + "…",
                "driver": v.get("Driver", ""),
                "used": ", ".join(u) if u else Text("unused", style="dim"),
                "size": fmt.human_size(size) if size is not None and size >= 0 else Text("…", style="dim"),
                "created": (v.get("CreatedAt") or "")[:16].replace("T", " "),
                "mount": v.get("Mountpoint", ""),
            }
            rows.append(Row(name, cells, {"size": size or 0, "used": len(u), "name": name.lower()},
                            data={"name": name, "users": u}))
        return rows

    def row_title(self, row: Row) -> str:
        return row.key

    def action_remove(self) -> None:
        row = self.selected
        if not row:
            return
        name, users = row.data["name"], row.data["users"]
        if users:
            return self.dapp.notify(f"Volume is in use by {', '.join(users)}", severity="warning")
        self.dapp.confirm(f"Remove volume {name}?", "Its data will be deleted permanently.",
                          lambda _: self.dapp.run_docker(lambda: self.dapp.svc.remove_volume(name),
                                                         ok=f"Removed volume {name}", kinds=("volume",)))

    def _unused(self) -> tuple[list[dict], list[dict]]:
        """(all unused volumes, unused anonymous volumes)"""
        volumes, _ = self.data
        rows = self.table.by_key
        unused = [v for v in volumes if v["Name"] in rows and not rows[v["Name"]].data["users"]]
        return unused, [v for v in unused if "com.docker.volume.anonymous" in (v.get("Labels") or {})]

    def cleanup_options(self) -> list[CleanupOption]:
        unused, anon = self._unused()
        df = self.dapp.meters.df
        sizes = {x["Name"]: max(0, (x.get("UsageData") or {}).get("Size", 0))
                 for x in (df or {}).get("Volumes") or []}

        def size(vs):
            return sum(sizes.get(v["Name"], 0) for v in vs) if df else None

        def label(v):
            n = v["Name"]
            return n if len(n) < 40 else n[:12] + "…"

        return [
            CleanupOption("anon", "Remove unused anonymous volumes", [label(v) for v in anon], size(anon),
                          noun="anonymous volumes",
                          note="Unnamed volumes left behind by removed containers."),
            CleanupOption("all", "Remove ALL unused volumes", [label(v) for v in unused], size(unused),
                          noun="volumes not used by any container",
                          note="Includes named volumes (e.g. databases of stopped compose projects). "
                               "Their data is deleted permanently."),
        ]

    def run_cleanup(self, option_id: str) -> None:
        anon = [v["Name"] for v in self._unused()[1]]
        self.dapp.run_docker(lambda: self.dapp.svc.prune_volumes(all_unused=option_id == "all", anonymous=anon),
                             ok=lambda r: f"Deleted {len(r.get('VolumesDeleted') or [])} volumes, "
                                          f"reclaimed {fmt.human_size(r.get('SpaceReclaimed', 0))}",
                             kinds=("volume",), refresh_df=True)
