"""Regenerate the screenshots in docs/assets/ from fake demo data.

    python docs/screenshots.py            # needs google-chrome (or chromium) for SVG -> PNG

Uses an in-memory Docker stand-in, so the images never show real containers
and come out identical on every machine.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from whaletop.app import WhaletopApp
from whaletop.docker_client import Stream

ASSETS = Path(__file__).parent / "assets"
SIZE = (182, 26)
FRAME = 0.2  # seconds between fake stats frames
GiB, MiB = 2**30, 2**20
NOW = time.time()


def ctr(cid, name, image, state="running", status="Up 3 hours", project=None, service=None,
        ports=(), created_ago=3 * 3600, mounts=()):
    labels = {}
    if project:
        labels = {
            "com.docker.compose.project": project,
            "com.docker.compose.service": service,
            "com.docker.compose.project.working_dir": f"/srv/{project}",
            "com.docker.compose.project.config_files": f"/srv/{project}/compose.yaml",
        }
    return {
        "Id": cid, "Names": [f"/{name}"], "Image": image, "ImageID": f"sha256:{image}",
        "State": state, "Status": status, "Created": NOW - created_ago, "Labels": labels,
        "Ports": [{"PrivatePort": c, "PublicPort": h, "Type": "tcp", "IP": ip} for h, c, ip in ports],
        "Mounts": [{"Type": "volume", "Name": m} for m in mounts],
        "NetworkSettings": {"Networks": {f"{project}_default" if project else "bridge": {}}},
    }


CONTAINERS = [
    ctr("c01", "shop-web-1", "shop/web:2.4", status="Up 3 hours (healthy)", project="shop", service="web",
        ports=[(8080, 80, "0.0.0.0")]),
    ctr("c02", "shop-api-1", "shop/api:2.4", status="Up 3 hours (healthy)", project="shop", service="api",
        ports=[(8000, 8000, "127.0.0.1")]),
    ctr("c03", "shop-worker-1", "shop/api:2.4", project="shop", service="worker"),
    ctr("c04", "shop-postgres-1", "postgres:17-alpine", status="Up 3 hours (healthy)", project="shop",
        service="postgres", ports=[(None, 5432, "")], mounts=["shop_pgdata"]),
    ctr("c05", "shop-redis-1", "redis:7-alpine", status="Up 3 hours (healthy)", project="shop", service="redis",
        ports=[(None, 6379, "")]),
    ctr("c06", "shop-migrate-1", "shop/api:2.4", state="exited", status="Exited (0) 3 hours ago",
        project="shop", service="migrate"),
    ctr("c07", "grafana", "grafana/grafana:12.1", status="Up 2 days", ports=[(3000, 3000, "0.0.0.0")],
        created_ago=2 * 86400, mounts=["grafana-data"]),
    ctr("c08", "traefik", "traefik:v3.5", status="Up 2 days", ports=[(80, 80, "0.0.0.0"), (443, 443, "0.0.0.0")],
        created_ago=2 * 86400),
    ctr("c09", "backup-job", "restic/restic:0.18", state="exited", status="Exited (0) 5 hours ago",
        created_ago=5 * 3600),
]

# (cpu %, memory bytes, rx B/s, tx B/s, read B/s, write B/s, pids)
LOAD = {
    "c01": (2.1, 48 * MiB, 18_000, 240_000, 0, 0, 9),
    "c02": (37.4, 212 * MiB, 95_000, 61_000, 0, 12_000, 23),
    "c03": (64.8, 305 * MiB, 4_000, 2_000, 0, 180_000, 11),
    "c04": (8.9, 410 * MiB, 52_000, 88_000, 1_400_000, 900_000, 14),
    "c05": (1.3, 22 * MiB, 30_000, 41_000, 0, 0, 6),
    "c07": (3.2, 156 * MiB, 7_000, 15_000, 0, 4_000, 18),
    "c08": (0.6, 38 * MiB, 260_000, 255_000, 0, 0, 7),
}

IMAGES = [
    {"Id": "sha256:shop/web:2.4", "RepoTags": ["shop/web:2.4"], "Size": 182 * MiB, "Created": NOW - 86400},
    {"Id": "sha256:shop/api:2.4", "RepoTags": ["shop/api:2.4"], "Size": 611 * MiB, "Created": NOW - 86400},
    {"Id": "sha256:shop/api:2.3", "RepoTags": ["shop/api:2.3"], "Size": 609 * MiB, "Created": NOW - 9 * 86400},
    {"Id": "sha256:postgres:17-alpine", "RepoTags": ["postgres:17-alpine"], "Size": 278 * MiB,
     "Created": NOW - 20 * 86400},
    {"Id": "sha256:redis:7-alpine", "RepoTags": ["redis:7-alpine"], "Size": 41 * MiB, "Created": NOW - 30 * 86400},
    {"Id": "sha256:grafana/grafana:12.1", "RepoTags": ["grafana/grafana:12.1"], "Size": 694 * MiB,
     "Created": NOW - 40 * 86400},
    {"Id": "sha256:traefik:v3.5", "RepoTags": ["traefik:v3.5"], "Size": 186 * MiB, "Created": NOW - 35 * 86400},
    {"Id": "sha256:restic/restic:0.18", "RepoTags": ["restic/restic:0.18"], "Size": 49 * MiB,
     "Created": NOW - 60 * 86400},
    {"Id": "sha256:3f9a1c0d2b7e", "RepoTags": None, "RepoDigests": [], "Size": 598 * MiB, "Created": NOW - 12 * 86400},
    {"Id": "sha256:8be27f04c1a9", "RepoTags": None, "RepoDigests": [], "Size": 601 * MiB, "Created": NOW - 15 * 86400},
    {"Id": "sha256:node:22-alpine", "RepoTags": ["node:22-alpine"], "Size": 157 * MiB, "Created": NOW - 50 * 86400},
]

LOG_LINES = [
    "2026-10-09T08:14:02Z INFO  uvicorn: Started server process [1]",
    "2026-10-09T08:14:02Z INFO  uvicorn: Waiting for application startup.",
    "2026-10-09T08:14:03Z INFO  app: connected to postgres at shop-postgres-1:5432",
    "2026-10-09T08:14:03Z INFO  app: connected to redis at shop-redis-1:6379",
    "2026-10-09T08:14:03Z INFO  uvicorn: Application startup complete.",
    "2026-10-09T08:14:03Z INFO  uvicorn: Uvicorn running on http://0.0.0.0:8000",
] + [
    f'2026-10-09T08:{15 + i * 9 // 60:02d}:{i * 9 % 60:02d}Z INFO  access: 172.18.0.{5 + i % 3} '
    f'"{m} {p} HTTP/1.1" {s} {t}ms'
    for i, (m, p, s, t) in enumerate([
        ("GET", "/api/products?page=1", 200, 12), ("GET", "/api/products/381", 200, 4),
        ("POST", "/api/cart", 201, 18), ("GET", "/api/cart", 200, 6), ("POST", "/api/checkout", 202, 141),
        ("GET", "/api/orders/77812", 200, 9), ("GET", "/api/health", 200, 1),
        ("GET", "/api/products?page=2", 200, 15), ("POST", "/api/login", 401, 22),
        ("POST", "/api/login", 200, 31), ("GET", "/api/me", 200, 3),
        ("GET", "/api/products/1204", 404, 2), ("GET", "/api/health", 200, 1),
    ])
] + ["2026-10-09T08:17:12Z WARN  payments: provider latency 1.8s above threshold (1.0s)",
     '2026-10-09T08:17:13Z INFO  access: 172.18.0.6 "POST /api/checkout HTTP/1.1" 202 1904ms']


def stats_frame(n: int, cpu: float, mem: int, rx: float, tx: float, rd: float, wr: float, pids: int) -> dict:
    """A frame whose deltas against the previous one reproduce exactly `cpu` percent."""
    online, sys_step = 8, 10**9
    return {
        "cpu_stats": {"cpu_usage": {"total_usage": int(n * cpu / 100 / online * sys_step)},
                      "system_cpu_usage": n * sys_step, "online_cpus": online},
        "precpu_stats": {"cpu_usage": {"total_usage": int((n - 1) * cpu / 100 / online * sys_step)},
                         "system_cpu_usage": (n - 1) * sys_step, "online_cpus": online},
        "memory_stats": {"usage": mem, "limit": 16 * GiB, "stats": {"inactive_file": 0}},
        # counters grow by rate * FRAME per frame, so whaletop computes exactly `rx` B/s etc.
        "networks": {"eth0": {"rx_bytes": int(n * rx * FRAME), "tx_bytes": int(n * tx * FRAME)}},
        "blkio_stats": {"io_service_bytes_recursive": [{"op": "read", "value": int(n * rd * FRAME)},
                                                       {"op": "write", "value": int(n * wr * FRAME)}]},
        "pids_stats": {"current": pids},
    }


class DemoDocker:
    host = None

    def __init__(self):
        self._stop = threading.Event()

    def cli_env(self):
        return {}

    def info(self):
        return {"NCPU": 8, "MemTotal": 16 * GiB, "Name": "prod-01"}

    def version(self):
        return {"Version": "29.9.0"}

    def df(self):
        return {"Images": [dict(i, Containers=0) for i in IMAGES],
                "Volumes": [{"Name": "shop_pgdata", "UsageData": {"Size": 1_900 * MiB}},
                            {"Name": "grafana-data", "UsageData": {"Size": 85 * MiB}}],
                "Containers": [{"Id": "c06", "SizeRw": 12 * MiB}, {"Id": "c09", "SizeRw": 3 * MiB}],
                "BuildCache": [{"ID": "cache01", "Type": "regular", "Size": 2_400 * MiB, "InUse": False}]}

    def events(self):
        def gen():
            self._stop.wait()
            return
            yield
        return Stream(gen(), self._stop.set)

    def containers(self):
        return [dict(c) for c in CONTAINERS]

    def stats_stream(self, cid):
        n = 1000
        while not self._stop.is_set():
            yield stats_frame(n, *LOAD[cid])
            n += 1
            time.sleep(FRAME)

    def logs(self, cid, tail=500, timestamps=False):
        return Stream(iter(LOG_LINES))

    def images(self):
        return IMAGES

    def volumes(self):
        return [{"Name": "shop_pgdata", "Driver": "local", "Mountpoint": "/var/lib/docker/volumes/shop_pgdata/_data",
                 "CreatedAt": "2026-09-14T10:02:11Z", "Labels": {}},
                {"Name": "grafana-data", "Driver": "local",
                 "Mountpoint": "/var/lib/docker/volumes/grafana-data/_data", "CreatedAt": "2026-09-01T08:00:00Z",
                 "Labels": {}}]

    def networks(self):
        return [{"Id": "n1", "Name": "bridge", "Driver": "bridge", "Scope": "local",
                 "IPAM": {"Config": [{"Subnet": "172.17.0.0/16"}]}},
                {"Id": "n2", "Name": "shop_default", "Driver": "bridge", "Scope": "local",
                 "IPAM": {"Config": [{"Subnet": "172.18.0.0/16"}]}}]


def to_png(svg: str, out: Path) -> None:
    chrome = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
    if not chrome:
        raise SystemExit("need google-chrome or chromium to convert SVG to PNG")
    w, h = (float(x) for x in re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg).groups())
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "shot.html"
        page.write_text(f'<html><body style="margin:0;background:transparent">{svg}</body></html>')
        subprocess.run([chrome, "--headless", "--disable-gpu", "--hide-scrollbars",
                        "--default-background-color=00000000", "--force-device-scale-factor=2",
                        f"--window-size={int(w)},{int(h)}", f"--screenshot={out}", page.as_uri()],
                       check=True, capture_output=True)


async def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    docker = DemoDocker()
    app = WhaletopApp(docker)

    async def shot(name: str) -> None:
        await pilot.pause(0.3)
        svg = app.export_screenshot(title="whaletop")
        to_png(svg, ASSETS / f"{name}.png")
        print("wrote", ASSETS / f"{name}.png")

    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause(3)                      # let live stats arrive
        # a believable CPU history for the sparkline (it only fills in over minutes)
        app.meters.history.clear()
        app.meters.history.extend(9 + 6 * ((i * 7) % 5) / 4 + (i % 9) + 5 * (40 < i < 70) for i in range(120))
        app.meters.refresh()
        app.views["containers"].table.move_cursor(row=2)
        await shot("containers")

        await pilot.press("2")
        await pilot.pause(0.5)
        await pilot.press("X")
        await shot("cleanup")
        await pilot.press("escape")

        await pilot.press("1")
        await pilot.pause(0.3)
        table = app.views["containers"].table
        table.move_cursor(row=table._shown.index("c02"))   # shop-api-1
        await pilot.press("l")
        await pilot.pause(0.8)
        await shot("logs")
    docker._stop.set()


if __name__ == "__main__":
    asyncio.run(main())
