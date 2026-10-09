"""htop-style header: CPU/MEM meters on the left, engine summary on the right."""

from __future__ import annotations

from collections import deque
from typing import Any

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual.widget import Widget

from .. import format as fmt

SPARK = " ▁▂▃▄▅▆▇█"


class Meters(Widget):
    DEFAULT_CSS = """
    Meters { height: 4; padding: 0 1; background: $surface; }
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self.ncpu = 1
        self.mem_total = 0
        self.engine = ""
        self.host = ""
        self.cpu = 0.0          # sum of container CPU% (100 = one core)
        self.mem = 0
        self.counts: dict[str, int] = {}
        self.n_images = 0
        self.df: dict[str, Any] | None = None
        self.history: deque[float] = deque(maxlen=120)

    def set_info(self, info: dict[str, Any], version: dict[str, Any]) -> None:
        self.ncpu = info.get("NCPU") or 1
        self.mem_total = info.get("MemTotal") or 0
        self.engine = version.get("Version", "?")
        self.host = info.get("Name", "")
        self.refresh()

    def set_usage(self, cpu: float, mem: int, counts: dict[str, int], n_images: int | None = None) -> None:
        self.cpu, self.mem, self.counts = cpu, mem, counts
        if n_images is not None:
            self.n_images = n_images
        self.history.append(self.cpu_pct)
        self.refresh()

    def set_df(self, df: dict[str, Any]) -> None:
        self.df = df
        self.refresh()

    @property
    def cpu_pct(self) -> float:
        return self.cpu / self.ncpu

    def _spark(self, width: int) -> Text:
        """CPU history, scaled to the recent peak (at least 10%) so that typical
        low load is still visible; the peak is shown at the end."""
        width -= 6
        vals = list(self.history)[-width:]
        top = max([10.0, *vals])
        t = Text("".join(SPARK[min(8, int(v / top * 8 + (0.999 if v > 0 else 0)))] for v in vals),
                 style="green")
        return Text(" " * (width - len(vals))) + t + Text(f" {top:4.0f}%", style="dim")

    def _disk(self) -> Text:
        t = Text()
        if not self.df:
            return t.append("Disk: calculating…", style="dim")
        imgs = self.df.get("Images") or []
        img_size = sum(i.get("Size", 0) for i in imgs)
        img_unused = sum(i.get("Size", 0) for i in imgs if not i.get("Containers"))
        vols = self.df.get("Volumes") or []
        vol_size = sum(max(0, (v.get("UsageData") or {}).get("Size", 0)) for v in vols)
        ctr_size = sum(c.get("SizeRw", 0) or 0 for c in self.df.get("Containers") or [])
        cache = sum(b.get("Size", 0) for b in self.df.get("BuildCache") or [])
        t.append("Disk: ", style="bold cyan")
        t.append(f"images {fmt.human_size(img_size)}")
        t.append(f" ({fmt.human_size(img_unused)} reclaimable)", style="dim")
        t.append(f" · containers {fmt.human_size(ctr_size)} · volumes {fmt.human_size(vol_size)}"
                 f" · build cache {fmt.human_size(cache)}")
        return t

    def render(self):
        w = self.size.width - 2
        left_w = max(30, w // 2 - 2)
        cpu = fmt.meter("CPU", self.cpu_pct, f"{self.cpu_pct:.1f}% of {self.ncpu} cpu", left_w)
        mem_pct = self.mem / self.mem_total * 100 if self.mem_total else 0
        mem = fmt.meter("Mem", mem_pct, f"{fmt.human_size(self.mem)}/{fmt.human_size(self.mem_total)}", left_w)
        spark = Text("Hst ", style="bold cyan") + self._spark(left_w - 4)

        c = self.counts
        tasks = Text()
        tasks.append("Containers: ", style="bold cyan")
        tasks.append(f"{c.get('running', 0)} running", style="bold green")
        for state, style in (("paused", "yellow"), ("restarting", "dark_orange"), ("exited", "red"),
                             ("created", "cyan"), ("dead", "red")):
            if c.get(state):
                tasks.append(", ")
                tasks.append(f"{c[state]} {state}", style=style)
        tasks.append("   Images: ", style="bold cyan")
        tasks.append(str(self.n_images))
        engine = Text()
        engine.append("Engine: ", style="bold cyan")
        engine.append(f"{self.engine}  ")
        engine.append(self.host, style="dim")

        grid = Table.grid(expand=True, padding=(0, 2))
        grid.add_column(width=left_w, no_wrap=True)
        grid.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
        grid.add_row(cpu, tasks)
        grid.add_row(mem, self._disk())
        grid.add_row(spark, engine)
        return Group(grid)
