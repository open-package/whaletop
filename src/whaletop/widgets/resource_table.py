"""Sortable, filterable DataTable that keeps the cursor on the same row across refreshes,
plus `ResourceView`, the base class for every tab."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Input, Static

from ..bg import background

if TYPE_CHECKING:
    from ..app import WhaletopApp


@dataclass
class Column:
    key: str
    label: str
    width: int | None = None


@dataclass
class Row:
    key: str
    cells: dict[str, Any]
    sort: dict[str, Any] = field(default_factory=dict)
    data: Any = None
    parent: str | None = None  # key of the parent row, for tree tables

    def sort_value(self, col: str) -> Any:
        if col in self.sort:
            return self.sort[col]
        v = self.cells.get(col, "")
        return (v.plain if isinstance(v, Text) else str(v)).lower()

    def haystack(self) -> str:
        return " ".join(v.plain if isinstance(v, Text) else str(v) for v in self.cells.values()).lower()


class ResourceTable(DataTable):
    def __init__(self, columns: list[Column], sort_key: str, reverse: bool = False, **kw):
        super().__init__(cursor_type="row", zebra_stripes=True, **kw)
        self.cols = columns
        self.sort_key = sort_key
        self.reverse = reverse
        self.filter_text = ""
        self.tree_col: str | None = None  # column that gets ├ / └ connectors on child rows
        self._rows: list[Row] = []
        self._shown: list[str] = []
        self._shown_cells: dict[str, list[Any]] = {}
        self.by_key: dict[str, Row] = {}

    def on_mount(self) -> None:
        self._add_columns()

    def _add_columns(self) -> None:
        for c in self.cols:
            label = c.label
            if c.key == self.sort_key:
                label += " ▼" if self.reverse else " ▲"
            self.add_column(Text(label, style="bold"), key=c.key, width=c.width)

    # --- data ------------------------------------------------------------
    def set_rows(self, rows: list[Row]) -> None:
        self._rows = rows
        self.by_key = {r.key: r for r in rows}
        self.render_rows()

    def visible_rows(self) -> list[Row]:
        """Sorted rows; children follow their parent and are sorted among themselves.
        With a filter, a matching child keeps its parent visible and a matching parent
        shows all its children."""
        def key(r: Row):
            v = r.sort_value(self.sort_key)
            # None sorts last regardless of direction; the row key breaks ties so equal
            # values (e.g. images built in the same second) never swap places on refresh
            return (v is None, v if v is not None else 0, r.key)

        children: dict[str, list[Row]] = {}
        tops: list[Row] = []
        for r in self._rows:
            if r.parent and r.parent in self.by_key:
                children.setdefault(r.parent, []).append(r)
            else:
                tops.append(r)
        needle = self.filter_text.lower()
        match = (lambda r: needle in r.haystack()) if needle else (lambda r: True)
        out: list[Row] = []
        for top in sorted(tops, key=key, reverse=self.reverse):
            kids = sorted(children.get(top.key, []), key=key, reverse=self.reverse)
            if not match(top):
                kids = [k for k in kids if match(k)]
                if not kids:
                    continue
            out.append(top)
            out.extend(kids)
        return out

    def _cells(self, rows: list[Row], i: int) -> list[Any]:
        r = rows[i]
        cells = [r.cells.get(c.key, "") for c in self.cols]
        if r.parent and self.tree_col:
            last = i + 1 == len(rows) or rows[i + 1].parent != r.parent
            j = next(n for n, c in enumerate(self.cols) if c.key == self.tree_col)
            cells[j] = Text.assemble(("└ " if last else "├ ", "dim"), cells[j])
        return cells

    def render_rows(self) -> None:
        rows = self.visible_rows()
        keys = [r.key for r in rows]
        if keys == self._shown:
            # same rows, same order: patch changed cells only (no flicker, cursor untouched)
            for i, r in enumerate(rows):
                new = self._cells(rows, i)
                old = self._shown_cells.get(r.key)
                if new != old:
                    for c, v, o in zip(self.cols, new, old or [None] * len(new)):
                        if v != o:
                            self.update_cell(r.key, c.key, v, update_width=True)
                    self._shown_cells[r.key] = new
            return
        cur = self.selected
        scroll_y = self.scroll_y
        self.clear()
        self._shown_cells = {}
        for i, r in enumerate(rows):
            cells = self._cells(rows, i)
            self.add_row(*cells, key=r.key)
            self._shown_cells[r.key] = cells
        self._shown = keys
        if cur and cur.key in keys:
            self.move_cursor(row=keys.index(cur.key), scroll=False)
        self.scroll_to(y=scroll_y, animate=False)

    @property
    def selected(self) -> Row | None:
        if not self._shown or self.cursor_row is None or self.cursor_row >= len(self._shown):
            return None
        return self.by_key.get(self._shown[self.cursor_row])

    # --- sorting ---------------------------------------------------------
    def set_sort(self, key: str, reverse: bool | None = None) -> None:
        if reverse is None:
            reverse = (not self.reverse) if key == self.sort_key else self.reverse
        self.sort_key, self.reverse = key, reverse
        self.clear(columns=True)
        self._shown = []
        self._add_columns()
        self.render_rows()

    def cycle_sort(self, step: int) -> None:
        keys = [c.key for c in self.cols if c.label.strip()]
        i = keys.index(self.sort_key) if self.sort_key in keys else 0
        self.set_sort(keys[(i + step) % len(keys)], self.reverse)

    def on_data_table_header_selected(self, ev: DataTable.HeaderSelected) -> None:
        ev.stop()
        self.set_sort(str(ev.column_key.value))


class ResourceView(Vertical):
    """Base for a tab: table + filter input + status line. Subclasses implement
    `fetch()` (runs in a thread) and `build_rows(data)`."""

    DEFAULT_CSS = """
    ResourceView { height: 1fr; }
    ResourceView > ResourceTable { height: 1fr; }
    ResourceView > .status { height: 1; padding: 0 1; background: $panel; color: $text-muted; }
    ResourceView > Input { dock: bottom; display: none; }
    ResourceView > Input.visible { display: block; }
    """

    BINDINGS = [
        Binding("slash", "filter", "Filter", key_display="/"),
        Binding("f3,f4", "filter", "Filter", show=False),
        Binding("less_than_sign", "sort(-1)", "Sort ←", show=False, key_display="<"),
        Binding("greater_than_sign,f6", "sort(1)", "Sort", key_display=">"),
        Binding("I", "invert", "Invert", show=False),
        Binding("escape", "clear_filter", "Clear filter", show=False),
        Binding("X", "cleanup", "Clean up"),
    ]

    COLUMNS: list[Column] = []
    SORT = "name"
    REVERSE = False
    NOUN = "items"
    KIND = ""  # inspect kind

    def __init__(self, **kw):
        super().__init__(**kw)
        self.data: Any = None
        self._loading = False
        self._reload_pending = False
        self.table = ResourceTable(self.COLUMNS, self.SORT, self.REVERSE)

    @property
    def dapp(self) -> "WhaletopApp":
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        yield self.table
        yield Static("", classes="status")
        yield Input(placeholder="filter…  (enter: keep, esc: clear)")

    # --- loading ---------------------------------------------------------
    def reload(self) -> None:
        # coalesce: never more than one fetch in flight per view, plus one queued
        if self._loading:
            self._reload_pending = True
            return
        self._loading = True
        self._load()

    @background
    def _load(self) -> None:
        try:
            data = self.fetch()
        except Exception as e:  # daemon gone, permission denied, …
            self.app.call_from_thread(self._load_failed, f"{self.NOUN}: {e}")
            return
        self.app.call_from_thread(self._loaded, data)

    def _loaded(self, data: Any) -> None:
        self._loading = False
        self._apply(data)
        if self._reload_pending:
            self._reload_pending = False
            self.reload()

    def _load_failed(self, msg: str) -> None:
        self._loading = False
        self._reload_pending = False
        self.dapp.error(msg)

    def _apply(self, data: Any) -> None:
        self.data = data
        self.redraw()

    def redraw(self) -> None:
        if self.data is None:
            return
        self.table.set_rows(self.build_rows(self.data))
        self.update_status()

    def update_status(self) -> None:
        s = self.status_count()
        if self.table.filter_text:
            s += f"  ·  filter: {self.table.filter_text!r}"
        label = next((c.label for c in self.COLUMNS if c.key == self.table.sort_key), "")
        s += f"  ·  sort: {label} {'▼' if self.table.reverse else '▲'}"
        extra = self.status_extra()
        if extra:
            s += f"  ·  {extra}"
        self.query_one(".status", Static).update(s)

    def status_count(self) -> str:
        shown, total = len(self.table._shown), len(self.table._rows)
        return f"{total} {self.NOUN}" if shown == total else f"{shown}/{total} {self.NOUN}"

    def status_extra(self) -> str:
        return ""

    def fetch(self) -> Any:
        raise NotImplementedError

    def build_rows(self, data: Any) -> list[Row]:
        raise NotImplementedError

    @property
    def selected(self) -> Row | None:
        return self.table.selected

    def focus_table(self) -> None:
        self.table.focus()

    # --- filter / sort ---------------------------------------------------
    def action_filter(self) -> None:
        inp = self.query_one(Input)
        inp.add_class("visible")
        inp.value = self.table.filter_text
        inp.focus()

    @on(Input.Changed)
    def _filter_changed(self, ev: Input.Changed) -> None:
        self.table.filter_text = ev.value.strip()
        self.table.render_rows()
        self.update_status()

    @on(Input.Submitted)
    def _filter_submitted(self, ev: Input.Submitted) -> None:
        ev.input.remove_class("visible")
        self.table.focus()

    def action_clear_filter(self) -> None:
        inp = self.query_one(Input)
        inp.value = ""
        inp.remove_class("visible")
        self.table.focus()

    def on_key(self, ev) -> None:
        # Escape inside the filter input clears it
        if ev.key == "escape" and self.query_one(Input).has_focus:
            ev.stop()
            self.action_clear_filter()

    def action_sort(self, step: int) -> None:
        self.table.cycle_sort(step)
        self.update_status()

    def action_invert(self) -> None:
        self.table.set_sort(self.table.sort_key, not self.table.reverse)
        self.update_status()

    # --- shared actions --------------------------------------------------
    def action_inspect(self) -> None:
        row = self.selected
        if row is None or not self.KIND:
            return
        self.dapp.show_inspect(self.KIND, self.inspect_id(row), self.row_title(row))

    def action_cleanup(self) -> None:
        from ..screens.cleanup import CleanupScreen

        if self.data is None:
            self.dapp.notify("Still loading…", severity="warning")
            return
        options = self.cleanup_options()
        if not options:
            return

        def done(option_id: str | None) -> None:
            if option_id:
                self.run_cleanup(option_id)

        self.app.push_screen(CleanupScreen(f"Clean up {self.NOUN}", options), done)

    def cleanup_options(self) -> list:
        return []

    def run_cleanup(self, option_id: str) -> None:
        pass

    def inspect_id(self, row: Row) -> str:
        return row.key

    def row_title(self, row: Row) -> str:
        v = row.cells.get("name", row.key)
        return v.plain if isinstance(v, Text) else str(v)
