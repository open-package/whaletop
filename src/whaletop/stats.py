"""Per-container streaming stats, one daemon thread per running container."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator

from . import format as fmt


@dataclass
class Sample:
    cpu: float = 0.0
    mem: int = 0
    mem_limit: int = 0
    net_rx_rate: float = 0.0
    net_tx_rate: float = 0.0
    blk_r_rate: float = 0.0
    blk_w_rate: float = 0.0
    pids: int = 0

    @property
    def mem_pct(self) -> float:
        return self.mem / self.mem_limit * 100 if self.mem_limit else 0.0


def compute(cur: dict[str, Any], prev_io: tuple | None, now: float) -> tuple[Sample, tuple]:
    """Turn one raw stats frame into a Sample. prev_io carries counters for rates."""
    mem, limit = fmt.mem_usage(cur)
    rx, tx = fmt.net_bytes(cur)
    br, bw = fmt.blk_bytes(cur)
    s = Sample(cpu=fmt.cpu_percent(cur), mem=mem, mem_limit=limit,
               pids=(cur.get("pids_stats") or {}).get("current") or 0)
    if prev_io:
        t0, rx0, tx0, br0, bw0 = prev_io
        dt = now - t0
        if dt > 0:
            s.net_rx_rate = max(0, rx - rx0) / dt
            s.net_tx_rate = max(0, tx - tx0) / dt
            s.blk_r_rate = max(0, br - br0) / dt
            s.blk_w_rate = max(0, bw - bw0) / dt
    return s, (now, rx, tx, br, bw)


class StatsCollector:
    def __init__(self, stream_factory: Callable[[str], Iterator[dict[str, Any]]]):
        self._factory = stream_factory
        self._lock = threading.Lock()
        self._samples: dict[str, Sample] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._wanted: set[str] = set()

    def ensure(self, running_ids: Iterable[str]) -> None:
        """Start streams for newly running containers, forget stopped ones."""
        ids = set(running_ids)
        with self._lock:
            self._wanted = ids
            for gone in set(self._samples) - ids:
                self._samples.pop(gone, None)
            for cid in ids:
                t = self._threads.get(cid)
                if t is None or not t.is_alive():
                    t = threading.Thread(target=self._run, args=(cid,), daemon=True,
                                         name=f"stats-{cid[:12]}")
                    self._threads[cid] = t
                    t.start()

    def snapshot(self) -> dict[str, Sample]:
        with self._lock:
            return dict(self._samples)

    def _run(self, cid: str) -> None:
        prev_io = None
        try:
            for raw in self._factory(cid):
                with self._lock:
                    if cid not in self._wanted:
                        return
                sample, prev_io = compute(raw, prev_io, time.monotonic())
                with self._lock:
                    self._samples[cid] = sample
        except Exception:
            pass  # container went away or daemon hiccup; ensure() restarts us
        finally:
            with self._lock:
                if self._threads.get(cid) is threading.current_thread():
                    del self._threads[cid]
