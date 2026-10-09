from __future__ import annotations

from collections import Counter
from typing import Any

from rich.text import Text
from textual.binding import Binding

from .. import format as fmt
from ..screens.cleanup import CleanupOption
from ..screens.dialogs import PullScreen, RunScreen
from ..widgets.resource_table import Column, ResourceView, Row


class ImagesView(ResourceView):
    COLUMNS = [
        Column("repo", "REPOSITORY"),
        Column("tag", "TAG"),
        Column("id", "IMAGE ID", 12),
        Column("size", "SIZE"),
        Column("created", "CREATED"),
        Column("used", "IN USE"),
    ]
    SORT = "repo"
    NOUN = "images"
    KIND = "image"
    BINDINGS = [
        Binding("P", "pull", "Pull"),
        Binding("R", "run", "Run"),
        Binding("d,delete", "remove", "Remove"),
        Binding("i", "inspect", "Inspect"),
    ]

    def fetch(self) -> tuple[list, list]:
        svc = self.dapp.svc
        return svc.images(), svc.containers()

    def _apply(self, data: Any) -> None:
        super()._apply(data)
        self.dapp.meters.n_images = len(data[0])
        self.dapp.meters.refresh()

    def build_rows(self, data) -> list[Row]:
        images, containers = data
        used = Counter(c.get("ImageID") for c in containers)
        rows = []
        for img in images:
            tags = [t for t in (img.get("RepoTags") or []) if t != "<none>:<none>"]
            n = used.get(img["Id"], 0)
            base = {
                "id": fmt.short_id(img["Id"]),
                "size": fmt.human_size(img.get("Size")),
                "created": fmt.ago(img.get("Created")),
                "used": Text(f"{n} container{'s' if n != 1 else ''}", style="green") if n
                else Text("unused", style="dim"),
            }
            sort = {"size": img.get("Size", 0), "created": img.get("Created", 0), "used": n}
            for ref in tags or [None]:
                if ref:
                    repo, _, tag = ref.rpartition(":")
                else:
                    digests = img.get("RepoDigests") or []
                    repo, tag = (digests[0].split("@")[0] if digests else "<none>"), "<none>"
                cells = dict(base, repo=repo, tag=Text(tag, style="dim") if tag == "<none>" else tag)
                # untagged images go after named ones; same repo sorts by tag
                row_sort = dict(sort, repo=(repo == "<none>", repo.lower(), tag.lower()),
                                tag=(tag == "<none>", tag.lower()))
                rows.append(Row(f"{img['Id']}|{ref or ''}", cells, row_sort,
                                data={"id": img["Id"], "ref": ref, "tags": tags, "used": n}))
        return rows

    def status_extra(self) -> str:
        if not self.data:
            return ""
        total = sum(i.get("Size", 0) for i in self.data[0])
        return f"total {fmt.human_size(total)}"

    def inspect_id(self, row: Row) -> str:
        return row.data["id"]

    def row_title(self, row: Row) -> str:
        return row.data["ref"] or fmt.short_id(row.data["id"])

    def action_pull(self) -> None:
        row = self.selected
        self.app.push_screen(PullScreen(row.data["ref"] if row and row.data["ref"] else ""))

    def action_run(self) -> None:
        row = self.selected
        if row:
            self.app.push_screen(RunScreen(row.data["ref"] or row.data["id"]))

    def action_remove(self) -> None:
        row = self.selected
        if not row:
            return
        d = row.data
        # an image with several tags is untagged one ref at a time
        target = d["ref"] if d["ref"] and len(d["tags"]) > 1 else d["id"]
        title = self.row_title(row)
        msg = f"In use by {d['used']} container(s)." if d["used"] else ""
        if len(d["tags"]) > 1:
            msg += f" Only the tag {d['ref']} will be removed."
        choices = [("yes", "Remove", "error")]
        if d["used"]:
            choices = [("force", "Force remove", "error")]

        def done(choice):
            force = choice == "force"
            self.dapp.run_docker(lambda: self.dapp.svc.remove_image(target, force=force),
                                 ok=f"Removed {title}", kinds=("image",))

        self.dapp.confirm(f"Remove image {title}?", msg.strip(), done, choices=choices)

    def cleanup_options(self) -> list[CleanupOption]:
        images, containers = self.data
        used = {c.get("ImageID") for c in containers}
        unused = [img for img in images if img["Id"] not in used]

        def label(img):
            tags = [t for t in (img.get("RepoTags") or []) if t != "<none>:<none>"]
            return ", ".join(tags) if tags else f"<none> {fmt.short_id(img['Id'])}"

        dangling = [img for img in unused if not [t for t in (img.get("RepoTags") or [])
                                                  if t != "<none>:<none>"]]
        df = self.dapp.meters.df
        cache = [b for b in (df or {}).get("BuildCache") or [] if not b.get("InUse")]
        note_shared = "Sizes include layers shared with other images, so less may be freed."
        return [
            CleanupOption("dangling", "Remove dangling images", [label(i) for i in dangling],
                          sum(i.get("Size", 0) for i in dangling), True, noun="untagged images",
                          note="Untagged leftovers from rebuilds and re-pulls. Safe to remove."),
            CleanupOption("unused", "Remove ALL unused images", [label(i) for i in unused],
                          sum(i.get("Size", 0) for i in unused), True, noun="images not used by any container",
                          note=note_shared + " Removed images must be pulled or rebuilt again."),
            CleanupOption("cache", "Clear build cache", [f"{b.get('Type', 'cache')} {b.get('ID', '')[:12]}"
                                                         for b in cache],
                          sum(b.get("Size", 0) for b in cache) if df else None, noun="unused build cache entries",
                          note="" if df else "Build cache list loads with the disk summary; try again shortly."),
        ]

    def run_cleanup(self, option_id: str) -> None:
        svc = self.dapp.svc
        if option_id == "cache":
            self.dapp.run_docker(lambda: svc.prune_builds(),
                                 ok=lambda r: f"Cleared {len(r.get('CachesDeleted') or [])} build cache entries, "
                                              f"reclaimed {fmt.human_size(r.get('SpaceReclaimed', 0))}",
                                 kinds=(), refresh_df=True)
            return
        self.dapp.run_docker(lambda: svc.prune_images(all_unused=option_id == "unused"),
                             ok=lambda r: f"Deleted {len(r.get('ImagesDeleted') or [])} images/layers, "
                                          f"reclaimed {fmt.human_size(r.get('SpaceReclaimed', 0))}",
                             kinds=("image",), refresh_df=True)
