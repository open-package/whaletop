"""Formatting helpers and stats math (same formulas as `docker stats`)."""

from __future__ import annotations

import re
import time
from typing import Any

from rich.text import Text

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\r")

STATE_STYLE = {
    "running": "green",
    "paused": "yellow",
    "restarting": "dark_orange",
    "created": "cyan",
    "exited": "red",
    "dead": "red",
    "removing": "magenta",
}


def human_size(n: float | int | None, unit: str = "B") -> str:
    """1536 -> '1.5K'. Compact, htop-style binary units."""
    if n is None or n < 0:
        return "-"
    n = float(n)
    for suffix in ("", "K", "M", "G", "T"):
        if n < 1024 or suffix == "T":
            if suffix == "":
                return f"{int(n)}{unit}"
            return f"{n:.1f}{suffix}" if n < 100 else f"{n:.0f}{suffix}"
        n /= 1024
    return f"{n:.1f}P"


def ago(ts: float | int | None) -> str:
    if not ts:
        return "-"
    delta = max(0, time.time() - float(ts))
    for size, name in ((86400 * 365, "y"), (86400 * 30, "mo"), (86400 * 7, "w"),
                       (86400, "d"), (3600, "h"), (60, "m")):
        if delta >= size:
            return f"{int(delta // size)}{name} ago"
    return f"{int(delta)}s ago"


def strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def short_id(id_: str) -> str:
    return id_.split(":", 1)[-1][:12]


# --- stats ---------------------------------------------------------------

def cpu_percent(s: dict[str, Any]) -> float:
    cpu = s.get("cpu_stats") or {}
    pre = s.get("precpu_stats") or {}
    try:
        cpu_delta = cpu["cpu_usage"]["total_usage"] - pre["cpu_usage"]["total_usage"]
        sys_delta = cpu["system_cpu_usage"] - pre["system_cpu_usage"]
    except (KeyError, TypeError):
        return 0.0
    online = cpu.get("online_cpus") or len(cpu.get("cpu_usage", {}).get("percpu_usage") or []) or 1
    if cpu_delta <= 0 or sys_delta <= 0:
        return 0.0
    return cpu_delta / sys_delta * online * 100.0


def mem_usage(s: dict[str, Any]) -> tuple[int, int]:
    """(usage minus page cache, limit) — matches the docker CLI on cgroup v1 and v2."""
    m = s.get("memory_stats") or {}
    usage = m.get("usage") or 0
    st = m.get("stats") or {}
    cache = st.get("inactive_file", st.get("total_inactive_file", 0)) or 0
    if cache < usage:
        usage -= cache
    return usage, m.get("limit") or 0


def net_bytes(s: dict[str, Any]) -> tuple[int, int]:
    rx = tx = 0
    for iface in (s.get("networks") or {}).values():
        rx += iface.get("rx_bytes", 0)
        tx += iface.get("tx_bytes", 0)
    return rx, tx


def blk_bytes(s: dict[str, Any]) -> tuple[int, int]:
    rd = wr = 0
    for e in (s.get("blkio_stats") or {}).get("io_service_bytes_recursive") or []:
        op = (e.get("op") or "").lower()
        if op == "read":
            rd += e.get("value", 0)
        elif op == "write":
            wr += e.get("value", 0)
    return rd, wr


# --- rendering -----------------------------------------------------------

def pct_style(pct: float) -> str:
    if pct >= 80:
        return "bold red"
    if pct >= 50:
        return "yellow"
    return "green"


def meter(label: str, pct: float, text: str, width: int) -> Text:
    """htop meter: `CPU[|||||||          23.4%]`."""
    width = max(width, len(label) + len(text) + 4)
    inner = width - len(label) - 2
    pct = max(0.0, min(pct, 100.0))
    filled = int(round(inner * pct / 100))
    bar = ("|" * filled).ljust(inner)
    # overlay the text on the right side of the bar, like htop
    bar = bar[: inner - len(text)] + text
    out = Text()
    out.append(label, style="bold cyan")
    out.append("[", style="bold")
    out.append(bar[:filled], style=pct_style(pct))
    out.append(bar[filled:], style="dim" if filled < inner - len(text) else "")
    out.append("]", style="bold")
    # the text should always be readable
    out.stylize("bold", len(label) + 1 + inner - len(text), len(label) + 1 + inner)
    return out


def mini_bar(pct: float, width: int = 6) -> Text:
    pct = max(0.0, pct)
    filled = int(round(width * min(pct, 100.0) / 100))
    t = Text()
    t.append(f"{pct:5.1f} ", style=pct_style(pct))
    t.append("▮" * filled, style=pct_style(pct))
    t.append("·" * (width - filled), style="dim")
    return t


def state_dot(state: str) -> Text:
    return Text("●", style=STATE_STYLE.get(state, "white"))


def ports_split(ports: list[dict[str, Any]] | None) -> tuple[Text, Text]:
    """(host ports, container ports) as two position-aligned lists.

    Published ports pair up as host 8080 ↔ container 80/tcp; exposed-but-unpublished
    ports show "-" on the host side. A host IP is shown only when it isn't a wildcard."""
    pairs: list[tuple[str, str]] = []
    for p in sorted(ports or [], key=lambda p: (p.get("PublicPort") is None, p.get("PrivatePort", 0))):
        priv, pub, typ = p.get("PrivatePort"), p.get("PublicPort"), p.get("Type", "tcp")
        ip = p.get("IP", "")
        host = "-" if not pub else (f"{ip}:{pub}" if ip and ip not in ("0.0.0.0", "::") else str(pub))
        pair = (host, f"{priv}/{typ}")
        if pair not in pairs:  # docker lists IPv4 and IPv6 bindings separately
            pairs.append(pair)
    host, ctr = Text(), Text()
    for i, (h, c) in enumerate(pairs):
        if i:
            host.append(", ", style="dim")
            ctr.append(", ", style="dim")
        host.append(h, style="dim" if h == "-" else "bold cyan")
        ctr.append(c)
    return host, ctr
