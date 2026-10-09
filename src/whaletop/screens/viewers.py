"""Full-screen viewers: streaming logs / command output, JSON inspect, help."""

from __future__ import annotations

import json
import threading
from collections import deque
from typing import Callable

from rich.syntax import Syntax
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Input, Log, Static

from .. import format as fmt
from ..docker_client import Stream

MAX_LINES = 10_000


class LogScreen(Screen[None]):
    """Follows a line stream (container logs or a compose command's output)."""

    DEFAULT_CSS = """
    LogScreen > .title { height: 1; background: $accent; color: $text; padding: 0 1; text-style: bold; }
    LogScreen > Log { height: 1fr; }
    LogScreen > Input { dock: bottom; display: none; }
    LogScreen > Input.visible { display: block; }
    """
    BINDINGS = [
        Binding("escape,q", "close", "Back"),
        Binding("slash", "search", "Filter", key_display="/"),
        Binding("f", "toggle_follow", "Follow"),
        Binding("t", "toggle_ts", "Timestamps"),
        Binding("c", "clear", "Clear"),
        Binding("g", "top", "Top", show=False),
        Binding("G", "bottom", "Bottom", show=False),
    ]

    def __init__(self, title: str, open_stream: Callable[[bool], Stream], timestamps_supported: bool = True):
        """open_stream(timestamps) -> Stream of str lines."""
        super().__init__()
        self.title_text = title
        self.open_stream = open_stream
        self.ts_supported = timestamps_supported
        self.timestamps = False
        self.follow = True
        self.lines: list[str] = []
        self.filter = ""
        self._stream: Stream | None = None
        self._gen = 0
        self._queue: deque[tuple[int, str]] = deque()

    def compose(self) -> ComposeResult:
        yield Static("", classes="title")
        yield Log(highlight=False, max_lines=MAX_LINES)
        yield Input(placeholder="show only lines containing…")
        yield Footer()

    def on_mount(self) -> None:
        self._update_title()
        self.set_interval(0.1, self._drain)
        self._start()

    def _update_title(self) -> None:
        flags = ["follow" if self.follow else "paused"]
        if self.timestamps:
            flags.append("timestamps")
        if self.filter:
            flags.append(f"filter {self.filter!r}")
        self.query_one(".title", Static).update(f"{self.title_text}   [{', '.join(flags)}]")

    def _start(self) -> None:
        self._stop_stream()
        self._gen += 1
        gen = self._gen
        self.lines.clear()
        self.query_one(Log).clear()
        threading.Thread(target=self._pump, args=(gen,), daemon=True).start()

    def _pump(self, gen: int) -> None:
        """Reader thread: pushes lines into a queue the UI drains on a timer, so a big
        backlog arrives in a few large writes instead of thousands of tiny ones."""
        try:
            self._stream = self.open_stream(self.timestamps)
            for line in self._stream:
                if gen != self._gen:
                    return
                self._queue.append((gen, fmt.strip_ansi(line)))
        except Exception as e:
            if gen == self._gen:
                self._queue.append((gen, f"── stream error: {e} ──"))

    def _drain(self) -> None:
        if not self._queue:
            return
        batch = []
        while self._queue:
            gen, line = self._queue.popleft()
            if gen == self._gen:
                batch.append(line)
        if not batch:
            return
        self.lines.extend(batch)
        if len(self.lines) > MAX_LINES:
            del self.lines[: len(self.lines) - MAX_LINES]
        f = self.filter.lower()
        shown = [l for l in batch if f in l.lower()] if f else batch
        if shown:
            self.query_one(Log).write_lines(shown, scroll_end=self.follow)

    def _rerender(self) -> None:
        log = self.query_one(Log)
        log.clear()
        f = self.filter.lower()
        log.write_lines([l for l in self.lines if f in l.lower()] if f else self.lines,
                        scroll_end=self.follow)
        self._update_title()

    def _stop_stream(self) -> None:
        if self._stream:
            s, self._stream = self._stream, None
            threading.Thread(target=s.close, daemon=True).start()

    def on_unmount(self) -> None:
        self._gen += 1
        self._stop_stream()

    def action_close(self) -> None:
        self.app.pop_screen()

    def action_search(self) -> None:
        inp = self.query_one(Input)
        inp.add_class("visible")
        inp.value = self.filter
        inp.focus()

    @on(Input.Changed)
    def _changed(self, ev: Input.Changed) -> None:
        self.filter = ev.value
        self._rerender()

    @on(Input.Submitted)
    def _submitted(self, ev: Input.Submitted) -> None:
        ev.input.remove_class("visible")
        self.query_one(Log).focus()

    def on_key(self, ev) -> None:
        inp = self.query_one(Input)
        if ev.key == "escape" and inp.has_focus:
            ev.stop()
            inp.value = ""
            inp.remove_class("visible")
            self.query_one(Log).focus()

    def action_toggle_follow(self) -> None:
        self.follow = not self.follow
        if self.follow:
            self.query_one(Log).scroll_end(animate=False)
        self._update_title()

    def action_toggle_ts(self) -> None:
        if not self.ts_supported:
            self.notify("Timestamps not available here")
            return
        self.timestamps = not self.timestamps
        self._update_title()
        self._start()

    def action_clear(self) -> None:
        self.lines.clear()
        self.query_one(Log).clear()

    def action_top(self) -> None:
        self.follow = False
        self.query_one(Log).scroll_home(animate=False)
        self._update_title()

    def action_bottom(self) -> None:
        self.follow = True
        self.query_one(Log).scroll_end(animate=False)
        self._update_title()


class InspectScreen(Screen[None]):
    DEFAULT_CSS = """
    InspectScreen > .title { height: 1; background: $accent; padding: 0 1; text-style: bold; }
    InspectScreen > VerticalScroll { height: 1fr; }
    """
    BINDINGS = [Binding("escape,q", "app.pop_screen", "Back")]

    def __init__(self, title: str, data: dict):
        super().__init__()
        self.title_text = title
        self.data = data

    def compose(self) -> ComposeResult:
        yield Static(self.title_text, classes="title")
        with VerticalScroll():
            yield Static(Syntax(json.dumps(self.data, indent=2, default=str), "json",
                                theme="ansi_dark", word_wrap=True, background_color="default"))
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(VerticalScroll).focus()


HELP = """\
[b cyan]whaletop[/] — htop-style terminal UI for Docker

[b]Global[/]
  [b]1-4[/]            Containers · Images · Volumes · Networks
  [b]] / [[/]          next / previous tab (or click a tab)
  [b]F5 / ctrl+r[/]    refresh everything
  [b]F1 / ?[/]         this help
  [b]q / F10[/]        quit

[b]Every list[/]
  [b]/ F3 F4[/]        filter (enter keeps it, esc clears)
  [b]> F6 / <[/]       next / previous sort column (or click a header)
  [b]I[/]              invert sort order
  [b]i[/]              inspect (JSON)
  [b]X[/]              clean up: preview what each prune option removes, then pick one

[b]Containers[/]  compose projects are groups (◆); standalone containers are plain rows
  [b]enter/space[/] expand / collapse a project (on a container: inspect)
  [b]s[/] start/stop   [b]r[/] restart   [b]l[/] logs   [b]d[/] remove        on a project row: whole stack
  [b]p[/] pause/unpause   [b]k F9[/] kill   [b]e[/] exec shell   [b]a[/] attach (detach: ctrl-p ctrl-q)
  [b]u[/] compose up -d   [b]D[/] down   [b]P[/] pull           project of the selected row
  [b]h[/] hide/show stopped

[b]Images[/]
  [b]P[/] pull   [b]R[/] run   [b]d[/] remove

[b]Volumes / Networks[/]
  [b]d[/] remove

[b]Clean up (X)[/]
  Containers: stopped containers · Images: dangling, all unused, build cache
  Volumes: unused anonymous, all unused · Networks: unused custom networks

[b]Logs viewer[/]
  [b]/[/] filter   [b]f[/] follow on/off   [b]t[/] timestamps   [b]c[/] clear   [b]g/G[/] top/bottom   [b]esc[/] back
"""


class HelpScreen(Screen[None]):
    DEFAULT_CSS = "HelpScreen { align: center middle; } HelpScreen > VerticalScroll { width: 92; height: auto; max-height: 100%; border: thick $accent; padding: 1 2; }"
    BINDINGS = [Binding("escape,q,f1,question_mark", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(Text.from_markup(HELP))
