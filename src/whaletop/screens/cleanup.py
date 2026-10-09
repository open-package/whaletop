"""Clean-up dialog: shows exactly what each prune option would remove before you pick one."""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from .. import format as fmt

PREVIEW_ITEMS = 8


@dataclass
class CleanupOption:
    id: str
    label: str                       # button text, e.g. "Remove stopped containers"
    items: list[str] = field(default_factory=list)  # names that will be removed
    size: int | None = None          # bytes reclaimed, None if unknown
    size_is_estimate: bool = False   # e.g. image sizes include shared layers
    note: str = ""                   # caveat shown under the summary
    noun: str = "items"
    has_size: bool = True            # False when removal frees no disk space (networks)


class CleanupScreen(ModalScreen[str | None]):
    DEFAULT_CSS = """
    CleanupScreen { align: center middle; background: $background 60%; }
    CleanupScreen > Vertical {
        width: 90; height: auto; max-height: 90%; padding: 1 2;
        border: thick $warning; background: $surface;
    }
    CleanupScreen .title { text-style: bold; margin-bottom: 1; }
    CleanupScreen VerticalScroll { height: auto; max-height: 30; }
    CleanupScreen .option { height: auto; margin-bottom: 1; padding: 0 1; border-left: wide $panel; }
    CleanupScreen .option Button { margin-top: 1; }
    CleanupScreen .buttons { height: auto; align-horizontal: right; }
    """
    BINDINGS = [Binding("escape,n", "cancel", "Cancel")]

    def __init__(self, title: str, options: list[CleanupOption]):
        super().__init__()
        self.title_text = title
        self.options = options

    @staticmethod
    def summary(o: CleanupOption) -> Text:
        n = len(o.items)
        if not n:
            return Text("Nothing to clean up.", style="dim")
        t = Text()
        t.append(f"{n} {o.noun}", style="bold")
        if not o.has_size:
            pass
        elif o.size is not None:
            t.append(f" · {'up to ' if o.size_is_estimate else ''}{fmt.human_size(o.size)} reclaimable",
                     style="bold green")
        else:
            t.append(" · size still being calculated", style="dim")
        shown = o.items[:PREVIEW_ITEMS]
        t.append("\n" + ", ".join(shown), style="")
        if n > len(shown):
            t.append(f", … and {n - len(shown)} more", style="dim")
        if o.note:
            t.append(f"\n{o.note}", style="italic yellow")
        return t

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.title_text, classes="title")
            with VerticalScroll():
                for o in self.options:
                    with Vertical(classes="option"):
                        yield Static(self.summary(o))
                        yield Button(o.label, id=f"c-{o.id}", variant="error", disabled=not o.items)
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        # never pre-select a destructive option: enter right after X must not delete anything
        self.query_one("#cancel", Button).focus()

    @on(Button.Pressed)
    def _pressed(self, ev: Button.Pressed) -> None:
        bid = ev.button.id or ""
        self.dismiss(bid[2:] if bid.startswith("c-") else None)

    def action_cancel(self) -> None:
        self.dismiss(None)
