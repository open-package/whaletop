"""A FakeDockerService with the same surface as DockerService, backed by dicts."""

from __future__ import annotations

import threading
import time

import pytest

from whaletop.docker_client import Stream


def container(cid, name, state="running", image="nginx:alpine", project=None, service=None, ports=None):
    labels = {}
    if project:
        labels = {
            "com.docker.compose.project": project,
            "com.docker.compose.service": service or name,
            "com.docker.compose.project.working_dir": "/nonexistent",
            "com.docker.compose.project.config_files": "/nonexistent/compose.yaml",
        }
    return {
        "Id": cid, "Names": [f"/{name}"], "Image": image, "ImageID": f"sha256:{image}",
        "State": state, "Status": "Up 5 minutes" if state == "running" else "Exited (0) 1 hour ago",
        "Created": time.time() - 300, "Labels": labels, "Ports": ports or [],
        "Mounts": [{"Type": "volume", "Name": "data"}] if name == "db" else [],
        "NetworkSettings": {"Networks": {"bridge": {"NetworkID": "net-bridge"}}},
    }


def stats_frame(cpu_total, sys_total, mem=50 * 2**20):
    return {
        "cpu_stats": {"cpu_usage": {"total_usage": cpu_total}, "system_cpu_usage": sys_total, "online_cpus": 4},
        "precpu_stats": {"cpu_usage": {"total_usage": cpu_total - 100}, "system_cpu_usage": sys_total - 1000,
                         "online_cpus": 4},
        "memory_stats": {"usage": mem + 4096, "limit": 1024 * 2**20, "stats": {"inactive_file": 4096}},
        "networks": {"eth0": {"rx_bytes": 1000, "tx_bytes": 500}},
        "blkio_stats": {"io_service_bytes_recursive": [{"op": "read", "value": 10}, {"op": "write", "value": 20}]},
        "pids_stats": {"current": 3},
    }


class FakeDockerService:
    host = None

    def __init__(self):
        self.calls: list[tuple] = []
        self._containers = [
            container("aaa111", "web", ports=[{"PrivatePort": 80, "PublicPort": 8080, "Type": "tcp"}]),
            container("bbb222", "db", image="postgres:16"),
            container("ccc333", "old-job", state="exited", image="alpine"),
            container("ddd444", "demo-api-1", project="demo", service="api"),
            container("eee555", "demo-cache-1", project="demo", service="cache", state="exited"),
        ]
        self._images = [
            {"Id": "sha256:nginx:alpine", "RepoTags": ["nginx:alpine"], "Size": 50 * 2**20, "Created": 1},
            {"Id": "sha256:postgres:16", "RepoTags": ["postgres:16"], "Size": 400 * 2**20, "Created": 2},
            {"Id": "sha256:dangling", "RepoTags": None, "RepoDigests": [], "Size": 10, "Created": 3},
        ]
        self._volumes = [{"Name": "data", "Driver": "local", "Mountpoint": "/x", "CreatedAt": "2026-01-01T00:00:00Z"},
                         {"Name": "scratch", "Driver": "local", "Mountpoint": "/y", "CreatedAt": ""}]
        self._networks = [
            {"Id": "net-bridge", "Name": "bridge", "Driver": "bridge", "Scope": "local",
             "IPAM": {"Config": [{"Subnet": "172.17.0.0/16"}]}},
            {"Id": "net-custom", "Name": "custom", "Driver": "bridge", "Scope": "local", "IPAM": {}},
        ]
        self._stop = threading.Event()

    def _rec(self, *a):
        self.calls.append(a)

    def cli_env(self):
        return {}

    def info(self):
        return {"NCPU": 4, "MemTotal": 8 * 2**30, "Name": "testhost"}

    def version(self):
        return {"Version": "99.0"}

    def df(self):
        return {"Images": self._images, "Volumes": [{"Name": "data", "UsageData": {"Size": 1234}}],
                "Containers": [], "BuildCache": []}

    def events(self):
        def gen():
            self._stop.wait()
            return
            yield
        return Stream(gen(), self._stop.set)

    def containers(self):
        return [dict(c) for c in self._containers]

    def _set_state(self, cid, state):
        for c in self._containers:
            if c["Id"] == cid:
                c["State"] = state

    def start(self, cid):
        self._rec("start", cid); self._set_state(cid, "running")

    def stop(self, cid):
        self._rec("stop", cid); self._set_state(cid, "exited")

    def restart(self, cid):
        self._rec("restart", cid)

    def pause(self, cid):
        self._rec("pause", cid); self._set_state(cid, "paused")

    def unpause(self, cid):
        self._rec("unpause", cid); self._set_state(cid, "running")

    def kill(self, cid):
        self._rec("kill", cid)

    def remove_container(self, cid, force=False):
        self._rec("remove_container", cid, force)
        self._containers = [c for c in self._containers if c["Id"] != cid]

    def prune_containers(self):
        self._rec("prune_containers")
        return {"ContainersDeleted": ["ccc333"], "SpaceReclaimed": 0}

    def prune_builds(self):
        self._rec("prune_builds")
        return {"CachesDeleted": [], "SpaceReclaimed": 0}

    def stats_stream(self, cid):
        for i in range(1, 4):
            yield stats_frame(1000 * i, 100000 * i)
            time.sleep(0.05)

    def logs(self, cid, tail=500, timestamps=False):
        return Stream(iter([f"line {i} from {cid}" for i in range(5)]))

    def inspect(self, kind, ident):
        return {"Kind": kind, "Id": ident}

    def images(self):
        return self._images

    def remove_image(self, ref, force=False):
        self._rec("remove_image", ref, force)

    def pull(self, ref):
        self._rec("pull", ref)
        return iter([{"status": "Pulling"}, {"status": "Done"}])

    def prune_images(self, all_unused):
        self._rec("prune_images", all_unused)
        return {"ImagesDeleted": [1], "SpaceReclaimed": 10}

    def volumes(self):
        return self._volumes

    def remove_volume(self, name, force=False):
        self._rec("remove_volume", name)

    def prune_volumes(self, all_unused, anonymous=None):
        self._rec("prune_volumes", all_unused)
        return {}

    def networks(self):
        return self._networks

    def remove_network(self, nid):
        self._rec("remove_network", nid)

    def prune_networks(self):
        self._rec("prune_networks")
        return {}

    def run(self, image, name, ports, env):
        self._rec("run", image, name, ports, env)
        return name or "x"

    def compose_argv(self, p, *args):
        return ["docker", "compose", "-p", p.name, *args]

    def popen_lines(self, argv, cwd=None):
        self._rec("popen", tuple(argv))
        return Stream(iter(["ok"]))


@pytest.fixture
def svc():
    s = FakeDockerService()
    yield s
    s._stop.set()
