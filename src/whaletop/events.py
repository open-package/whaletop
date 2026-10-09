"""Watch the docker event stream and report which resource kinds changed."""

from __future__ import annotations

import threading
from typing import Callable

from .docker_client import Stream

# events that don't change anything we display
IGNORED_ACTIONS = ("exec_create", "exec_start", "exec_die", "exec_detach", "top", "attach",
                   "resize", "archive-path", "extract-to-dir", "export", "commit")


class EventWatcher:
    def __init__(self, stream_factory: Callable[[], Stream], on_change: Callable[[str, str], None]):
        self._factory = stream_factory
        self._on_change = on_change
        self._stop = threading.Event()
        self._stream: Stream | None = None
        self._thread = threading.Thread(target=self._run, daemon=True, name="docker-events")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._stream:
            self._stream.close()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._stream = self._factory()
                for ev in self._stream:
                    if self._stop.is_set():
                        return
                    action = (ev.get("Action") or ev.get("status") or "").split(":")[0]
                    if action in IGNORED_ACTIONS:
                        continue
                    kind = ev.get("Type") or "container"
                    self._on_change(kind, action)
            except Exception:
                pass
            # stream ended (daemon restart?) — reconnect after a pause
            self._stop.wait(2.0)
