"""Run blocking Docker calls off the UI thread.

Textual thread workers are joined on exit, so one slow call (`/system/df` can take
30s on hosts with hundreds of images) would make quitting hang. Daemon threads don't."""

from __future__ import annotations

import functools
import threading


def background(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs) -> None:
        def run() -> None:
            try:
                fn(*args, **kwargs)
            except RuntimeError:
                pass  # app shut down while we were posting a result back

        threading.Thread(target=run, daemon=True, name=fn.__name__).start()

    return wrapper
