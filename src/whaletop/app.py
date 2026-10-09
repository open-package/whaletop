"""WhaletopApp: htop-style meters on top, resource tabs below, function-key footer."""

from __future__ import annotations

import subprocess
from typing import Any, Callable, Iterable

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, TabbedContent, TabPane

from .bg import background
from .docker_client import DockerService, Stream
from .events import EventWatcher
from .screens.dialogs import ChoiceScreen
from .screens.viewers import HelpScreen, InspectScreen, LogScreen
from .stats import StatsCollector
from .views.containers import ContainersView
from .views.images import ImagesView
from .views.networks import NetworksView
from .views.volumes import VolumesView
from .widgets.meters import Meters
from .widgets.resource_table import ResourceView

TABS = [
    ("containers", "1 Containers", ContainersView),
    ("images", "2 Images", ImagesView),
    ("volumes", "3 Volumes", VolumesView),
    ("networks", "4 Networks", NetworksView),
]

# which views to reload when the daemon reports a change to a kind of object
EVENT_VIEWS = {
    "container": {"containers"},
    "image": {"images"},
    "volume": {"volumes"},
    "network": {"networks"},
}
# container lifecycle events that change "in use" columns on the other tabs
CONTAINER_LIFECYCLE = {"create", "destroy", "rename"}

SHELL = "if command -v bash >/dev/null 2>&1; then exec bash; else exec sh; fi"


def explain(e: Exception) -> str:
    return str(getattr(e, "explanation", None) or e)


class WhaletopApp(App):
    TITLE = "whaletop"
    CSS = """
    Screen { background: $background; }
    TabbedContent { height: 1fr; }
    TabbedContent > ContentSwitcher { height: 1fr; }
    TabPane { padding: 0; height: 1fr; }
    """
    BINDINGS = [
        Binding("1", "tab('containers')", show=False),
        Binding("2", "tab('images')", show=False),
        Binding("3", "tab('volumes')", show=False),
        Binding("4", "tab('networks')", show=False),
        Binding("right_square_bracket", "cycle_tab(1)", show=False),
        Binding("left_square_bracket", "cycle_tab(-1)", show=False),
        Binding("f5,ctrl+r", "refresh_all", "Refresh", show=False),
        Binding("f1,question_mark", "help", "Help", key_display="?"),
        Binding("q,f10", "quit", "Quit"),
    ]

    def __init__(self, svc: DockerService):
        super().__init__()
        self.svc = svc
        self.stats = StatsCollector(svc.stats_stream)
        self.events = EventWatcher(svc.events, self._on_event)
        self.meters = Meters()
        self.views: dict[str, ResourceView] = {}
        self.containers: list[dict[str, Any]] = []
        self._dirty: set[str] = set()
        self._df_loading = False

    def compose(self) -> ComposeResult:
        yield self.meters
        with TabbedContent(initial="containers"):
            for tid, title, cls in TABS:
                with TabPane(title, id=tid):
                    view = cls(id=f"view-{tid}")
                    self.views[tid] = view
                    yield view
        yield Footer()

    def on_mount(self) -> None:
        self._load_info()
        self.action_refresh_all()
        self.events.start()
        self.set_interval(1.0, self._tick_stats)
        self.set_interval(0.3, self._flush_dirty)
        self.set_interval(5.0, lambda: self.mark_dirty("container"))  # safety net if events stall
        self.set_interval(30.0, self._refresh_slow)
        self.set_interval(120.0, self._load_df)
        self.views["containers"].focus_table()

    def on_unmount(self) -> None:
        self.events.stop()

    # --- data plumbing -----------------------------------------------------
    @background
    def _load_info(self) -> None:
        try:
            info, version = self.svc.info(), self.svc.version()
        except Exception as e:
            self.call_from_thread(self.error, explain(e))
            return
        self.call_from_thread(self.meters.set_info, info, version)

    def _load_df(self) -> None:
        # /system/df can take tens of seconds on hosts with many images: one at a time
        if not self._df_loading:
            self._df_loading = True
            self._fetch_df()

    @background
    def _fetch_df(self) -> None:
        try:
            df = self.svc.df()
        except Exception:
            df = None
        self.call_from_thread(self._apply_df, df)

    def _apply_df(self, df: dict[str, Any] | None) -> None:
        self._df_loading = False
        if df is None:
            return
        self.meters.set_df(df)
        self.views["volumes"].redraw()  # sizes come from df

    def _refresh_slow(self) -> None:
        for tid in ("images", "volumes", "networks"):
            self.views[tid].reload()

    def containers_loaded(self, containers: list[dict[str, Any]]) -> None:
        self.containers = containers
        self.stats.ensure(c["Id"] for c in containers if c.get("State") == "running")
        self._update_meters()

    def _update_meters(self) -> None:
        snap = self.stats.snapshot()
        counts: dict[str, int] = {}
        for c in self.containers:
            counts[c.get("State", "")] = counts.get(c.get("State", ""), 0) + 1
        self.meters.set_usage(sum(s.cpu for s in snap.values()), sum(s.mem for s in snap.values()), counts)

    def _tick_stats(self) -> None:
        self._update_meters()
        active = self.query_one(TabbedContent).active
        if active == "containers":
            self.views[active].redraw()

    def _on_event(self, kind: str, action: str) -> None:
        """Called from the events thread."""
        self.call_from_thread(self.mark_dirty, kind, action)

    def mark_dirty(self, kind: str, action: str = "") -> None:
        self._dirty |= EVENT_VIEWS.get(kind, set())
        if kind == "container" and action in CONTAINER_LIFECYCLE:
            self._dirty |= {"images", "volumes", "networks"}

    def _flush_dirty(self) -> None:
        if not self._dirty:
            return
        dirty, self._dirty = self._dirty, set()
        for tid in dirty:
            self.views[tid].reload()

    # --- helpers used by views ---------------------------------------------
    def error(self, msg: str) -> None:
        self.notify(msg, severity="error", timeout=8)

    @background
    def run_docker(self, fn: Callable[[], Any], ok: str | Callable[[Any], str] | None = None,
                   kinds: Iterable[str] = ("container",), refresh_df: bool = False) -> None:
        try:
            result = fn()
        except Exception as e:
            self.call_from_thread(self.error, explain(e))
        else:
            if ok:
                self.call_from_thread(self.notify, ok(result) if callable(ok) else ok)
            if refresh_df:
                self.call_from_thread(self._load_df)
        for k in kinds:
            self.call_from_thread(self.mark_dirty, k, "destroy")

    def confirm(self, title: str, message: str, on_yes: Callable[[str], None], *,
                label: str = "Yes", choices: list[tuple[str, str, str]] | None = None) -> None:
        def cb(choice: str | None) -> None:
            if choice:
                on_yes(choice)
        self.push_screen(ChoiceScreen(title, message, choices or [("yes", label, "error")]), cb)

    @background
    def show_inspect(self, kind: str, ident: str, title: str) -> None:
        try:
            data = self.svc.inspect(kind, ident)
        except Exception as e:
            self.call_from_thread(self.error, explain(e))
            return
        self.call_from_thread(self.push_screen, InspectScreen(f"{kind} {title}", data))

    def show_container_logs(self, cid: str, name: str) -> None:
        self.push_screen(LogScreen(f"logs: {name}", lambda ts: self.svc.logs(cid, timestamps=ts)))

    def show_command(self, title: str, argv: list[str], cwd: str | None = None,
                     timestamps_flag: str | None = None) -> None:
        def open_stream(ts: bool) -> Stream:
            args = list(argv)
            if ts and timestamps_flag:
                args.append(timestamps_flag)
            return self.svc.popen_lines(args, cwd=cwd)
        self.push_screen(LogScreen(title, open_stream, timestamps_supported=bool(timestamps_flag)))

    def _interactive(self, argv: list[str], banner: str) -> None:
        try:
            with self.suspend():
                print(f"\x1b[1;36m── whaletop: {banner} ──\x1b[0m", flush=True)
                subprocess.run(argv, env=self.svc.cli_env())
        except Exception as e:  # SuspendNotSupported (e.g. textual-web) or docker CLI missing
            self.error(f"Cannot open an interactive session here: {explain(e)}")
        self.mark_dirty("container")

    def exec_shell(self, cid: str, name: str) -> None:
        self._interactive(["docker", "exec", "-it", cid, "sh", "-c", SHELL],
                          f"shell in {name} (type exit to return)")

    def attach(self, cid: str, name: str) -> None:
        self._interactive(["docker", "attach", "--sig-proxy=false", cid],
                          f"attached to {name} (ctrl-p ctrl-q or ctrl-c to detach)")

    # --- actions -----------------------------------------------------------
    def action_tab(self, tid: str) -> None:
        self.query_one(TabbedContent).active = tid
        self.views[tid].focus_table()

    def action_cycle_tab(self, step: int) -> None:
        ids = [t[0] for t in TABS]
        cur = self.query_one(TabbedContent).active
        self.action_tab(ids[(ids.index(cur) + step) % len(ids)] if cur in ids else ids[0])

    @on(TabbedContent.TabActivated)
    def _tab_activated(self, ev: TabbedContent.TabActivated) -> None:
        tid = ev.pane.id or ""
        if tid in self.views:
            self.views[tid].focus_table()
            self.views[tid].reload()

    def action_refresh_all(self) -> None:
        self._load_df()
        for v in self.views.values():
            v.reload()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())
