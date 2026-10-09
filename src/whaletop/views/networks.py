from __future__ import annotations

from collections import defaultdict

from rich.text import Text
from textual.binding import Binding

from .. import format as fmt
from ..docker_client import BUILTIN_NETWORKS, container_name
from ..screens.cleanup import CleanupOption
from ..widgets.resource_table import Column, ResourceView, Row


class NetworksView(ResourceView):
    COLUMNS = [
        Column("name", "NAME"),
        Column("id", "NETWORK ID", 12),
        Column("driver", "DRIVER"),
        Column("scope", "SCOPE"),
        Column("subnet", "SUBNET"),
        Column("containers", "CONTAINERS"),
    ]
    SORT = "name"
    NOUN = "networks"
    KIND = "network"
    BINDINGS = [
        Binding("d,delete", "remove", "Remove"),
        Binding("i", "inspect", "Inspect"),
    ]

    def fetch(self) -> tuple[list, list]:
        svc = self.dapp.svc
        return svc.networks(), svc.containers()

    def build_rows(self, data) -> list[Row]:
        networks, containers = data
        members: dict[str, list[str]] = defaultdict(list)
        for c in containers:
            for net, cfg in ((c.get("NetworkSettings") or {}).get("Networks") or {}).items():
                members[(cfg or {}).get("NetworkID") or net].append(container_name(c))
        rows = []
        for n in networks:
            m = members.get(n["Id"]) or members.get(n["Name"]) or []
            ipam = (n.get("IPAM") or {}).get("Config") or []
            builtin = n["Name"] in BUILTIN_NETWORKS
            cells = {
                "name": Text(n["Name"], style="dim italic") if builtin else n["Name"],
                "id": fmt.short_id(n["Id"]),
                "driver": n.get("Driver", ""),
                "scope": n.get("Scope", ""),
                "subnet": ", ".join(c.get("Subnet", "") for c in ipam if c.get("Subnet")),
                "containers": ", ".join(m) if m else Text("—", style="dim"),
            }
            rows.append(Row(n["Id"], cells, {"containers": len(m)},
                            data={"name": n["Name"], "builtin": builtin, "members": m}))
        return rows

    def row_title(self, row: Row) -> str:
        return row.data["name"]

    def action_remove(self) -> None:
        row = self.selected
        if not row:
            return
        d = row.data
        if d["builtin"]:
            return self.dapp.notify(f"{d['name']} is a built-in network", severity="warning")
        if d["members"]:
            return self.dapp.notify(f"Network has connected containers: {', '.join(d['members'])}",
                                    severity="warning")
        nid = row.key
        self.dapp.confirm(f"Remove network {d['name']}?", "", lambda _: self.dapp.run_docker(
            lambda: self.dapp.svc.remove_network(nid), ok=f"Removed network {d['name']}", kinds=("network",)))

    def cleanup_options(self) -> list[CleanupOption]:
        unused = [r.data["name"] for r in self.table.by_key.values()
                  if not r.data["builtin"] and not r.data["members"]]
        return [CleanupOption("unused", "Remove unused networks", sorted(unused), None, noun="custom networks "
                              "with no containers", note="Built-in bridge, host and none are never removed.", has_size=False)]

    def run_cleanup(self, option_id: str) -> None:
        self.dapp.run_docker(lambda: self.dapp.svc.prune_networks(),
                             ok=lambda r: f"Deleted {len(r.get('NetworksDeleted') or [])} networks",
                             kinds=("network",))
