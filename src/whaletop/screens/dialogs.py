"""Small modal dialogs: choice/confirm, pull image, run container."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen

from ..bg import background
from textual.widgets import Button, Input, Label, Log

if TYPE_CHECKING:
    from ..app import WhaletopApp

DIALOG_CSS = """
{name} {{ align: center middle; background: $background 60%; }}
{name} > Vertical {{
    width: 72; height: auto; max-height: 90%; padding: 1 2;
    border: thick $accent; background: $surface;
}}
{name} .title {{ text-style: bold; margin-bottom: 1; }}
{name} .buttons {{ height: auto; margin-top: 1; align-horizontal: right; }}
{name} Button {{ margin-left: 1; }}
{name} Input {{ margin-bottom: 1; }}
"""


class ChoiceScreen(ModalScreen[str | None]):
    """Ask a question; dismisses with the chosen option's id, or None on cancel."""

    DEFAULT_CSS = DIALOG_CSS.format(name="ChoiceScreen")
    BINDINGS = [Binding("escape,n", "cancel", "Cancel"), Binding("left,h", "app.focus_previous", show=False),
                Binding("right,l", "app.focus_next", show=False)]

    def __init__(self, title: str, message: str = "", choices: list[tuple[str, str, str]] | None = None):
        """choices: (id, label, variant). Defaults to a destructive Yes/Cancel."""
        super().__init__()
        self.title_text = title
        self.message = message
        self.choices = choices or [("yes", "Yes", "error")]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.title_text, classes="title")
            if self.message:
                yield Label(self.message)
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel", variant="default")
                for cid, label, variant in self.choices:
                    yield Button(label, id=f"c-{cid}", variant=variant)  # type: ignore[arg-type]

    def on_mount(self) -> None:
        self.query(Button).last().focus()

    def key_y(self) -> None:
        if len(self.choices) == 1:
            self.dismiss(self.choices[0][0])

    @on(Button.Pressed)
    def _pressed(self, ev: Button.Pressed) -> None:
        bid = ev.button.id or ""
        self.dismiss(bid[2:] if bid.startswith("c-") else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class PullScreen(ModalScreen[None]):
    DEFAULT_CSS = DIALOG_CSS.format(name="PullScreen") + "PullScreen Log { height: 14; border: round $panel; }"
    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, ref: str = ""):
        super().__init__()
        self.ref = ref
        self._cancel = threading.Event()

    @property
    def dapp(self) -> "WhaletopApp":
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Pull image", classes="title")
            yield Input(self.ref, placeholder="e.g. nginx:latest, ghcr.io/org/app:1.2", id="ref")
            yield Log(highlight=False)
            with Horizontal(classes="buttons"):
                yield Button("Close", id="close")
                yield Button("Pull", id="pull", variant="primary")

    @on(Input.Submitted)
    @on(Button.Pressed, "#pull")
    def _start(self) -> None:
        ref = self.query_one("#ref", Input).value.strip()
        if ref:
            self.query_one("#pull", Button).disabled = True
            self._pull(ref)

    @on(Button.Pressed, "#close")
    def action_close(self) -> None:
        self._cancel.set()
        self.dismiss(None)

    @background
    def _pull(self, ref: str) -> None:
        log = self.query_one(Log)
        layers: dict[str, str] = {}
        say = lambda s: self.app.call_from_thread(log.write_line, s)  # noqa: E731
        say(f"Pulling {ref} …")
        try:
            for ev in self.dapp.svc.pull(ref):
                if self._cancel.is_set():
                    return
                if "error" in ev:
                    say(f"ERROR: {ev['error']}")
                    break
                lid, status = ev.get("id"), ev.get("status", "")
                # only log state transitions per layer, not every progress tick
                if lid and layers.get(lid) == status:
                    continue
                if lid:
                    layers[lid] = status
                say(f"{lid + ': ' if lid else ''}{status} {ev.get('progress', '') if not lid else ''}".rstrip())
            else:
                say("✔ done")
        except Exception as e:
            say(f"ERROR: {e}")
        finally:
            self.app.call_from_thread(self._done)

    def _done(self) -> None:
        if self.is_attached:
            self.query_one("#pull", Button).disabled = False
            self.dapp.mark_dirty("image")


class RunScreen(ModalScreen[None]):
    DEFAULT_CSS = DIALOG_CSS.format(name="RunScreen")
    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, image: str):
        super().__init__()
        self.image = image

    @property
    def dapp(self) -> "WhaletopApp":
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Run a new container", classes="title")
            yield Label("Image")
            yield Input(self.image, id="image")
            yield Label("Name (optional)")
            yield Input(placeholder="my-container", id="name")
            yield Label("Ports host:container, comma separated (optional)")
            yield Input(placeholder="8080:80, 5432:5432/tcp", id="ports")
            yield Label("Environment KEY=VALUE, comma separated (optional)")
            yield Input(placeholder="FOO=bar, DEBUG=1", id="env")
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="close")
                yield Button("Run", id="run", variant="success")

    def on_mount(self) -> None:
        self.query_one("#name", Input).focus()

    @staticmethod
    def parse_ports(text: str) -> dict[str, int]:
        ports: dict[str, int] = {}
        for part in filter(None, (p.strip() for p in text.split(","))):
            host, _, ctr = part.rpartition(":")
            if not host:
                raise ValueError(f"bad port mapping {part!r} (want host:container)")
            if "/" not in ctr:
                ctr += "/tcp"
            ports[ctr] = int(host)
        return ports

    @on(Button.Pressed, "#close")
    def action_close(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted)
    @on(Button.Pressed, "#run")
    def _run(self) -> None:
        get = lambda i: self.query_one(f"#{i}", Input).value.strip()  # noqa: E731
        try:
            ports = self.parse_ports(get("ports"))
        except ValueError as e:
            self.dapp.error(str(e))
            return
        env = [e.strip() for e in get("env").split(",") if e.strip()]
        image, name = get("image"), get("name")
        self.dapp.run_docker(lambda: self.dapp.svc.run(image, name, ports, env),
                             ok=lambda n: f"Started container {n}", kinds=("container",))
        self.dismiss(None)
