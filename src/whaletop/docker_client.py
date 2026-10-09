"""Thin wrapper over the docker SDK. The UI talks only to `DockerService`,
so tests can swap in a fake with the same methods."""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any, Iterator

import docker
from docker.errors import DockerException

logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("docker").setLevel(logging.ERROR)

COMPOSE_PROJECT = "com.docker.compose.project"
COMPOSE_SERVICE = "com.docker.compose.service"
COMPOSE_WORKDIR = "com.docker.compose.project.working_dir"
COMPOSE_FILES = "com.docker.compose.project.config_files"
BUILTIN_NETWORKS = {"bridge", "host", "none"}


def resolve_host(host: str | None = None) -> str | None:
    """DOCKER_HOST / --host win; otherwise use the docker CLI's current context
    (e.g. Docker Desktop's desktop-linux socket), which docker-py ignores."""
    if host:
        return host
    if os.environ.get("DOCKER_HOST"):
        return os.environ["DOCKER_HOST"]
    try:
        from docker.context import ContextAPI

        ctx = ContextAPI.get_current_context()
        if ctx and ctx.Host:
            return ctx.Host
    except Exception:
        pass
    return None


class Stream:
    """An iterator of lines/objects with an explicit close() for cancellation."""

    def __init__(self, it: Iterator[Any], close=None):
        self._it = it
        self._close = close

    def __iter__(self):
        return self._it

    def close(self) -> None:
        if self._close:
            try:
                self._close()
            except Exception:
                pass


@dataclass
class ComposeProject:
    name: str
    working_dir: str = ""
    config_files: list[str] = field(default_factory=list)
    containers: list[dict[str, Any]] = field(default_factory=list)

    @property
    def running(self) -> int:
        return sum(1 for c in self.containers if c.get("State") == "running")

    @property
    def services(self) -> list[str]:
        return sorted({(c.get("Labels") or {}).get(COMPOSE_SERVICE, "?") for c in self.containers})

    @property
    def files_exist(self) -> bool:
        return bool(self.config_files) and all(os.path.exists(f) for f in self.config_files)


def group_compose(containers: list[dict[str, Any]]) -> list[ComposeProject]:
    projects: dict[str, ComposeProject] = {}
    for c in containers:
        labels = c.get("Labels") or {}
        name = labels.get(COMPOSE_PROJECT)
        if not name:
            continue
        p = projects.setdefault(name, ComposeProject(name))
        p.containers.append(c)
        if not p.working_dir and labels.get(COMPOSE_WORKDIR):
            p.working_dir = labels[COMPOSE_WORKDIR]
        if not p.config_files and labels.get(COMPOSE_FILES):
            p.config_files = [f for f in labels[COMPOSE_FILES].split(",") if f]
    for p in projects.values():
        p.containers.sort(key=lambda c: (c.get("Labels") or {}).get(COMPOSE_SERVICE, ""))
    return sorted(projects.values(), key=lambda p: p.name)


def container_name(c: dict[str, Any]) -> str:
    names = c.get("Names") or []
    return names[0].lstrip("/") if names else c.get("Id", "")[:12]


class DockerService:
    def __init__(self, host: str | None = None):
        self.host = resolve_host(host)
        self.client = docker.DockerClient(base_url=self.host, max_pool_size=64) if self.host \
            else docker.from_env(max_pool_size=64)
        self.api = self.client.api
        self.api.ping()

    # env for docker CLI subprocesses so they talk to the same daemon
    def cli_env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.host and not os.environ.get("DOCKER_HOST"):
            env["DOCKER_HOST"] = self.host
        return env

    # --- system --------------------------------------------------------
    def info(self) -> dict[str, Any]:
        return self.api.info()

    def version(self) -> dict[str, Any]:
        return self.api.version()

    def df(self) -> dict[str, Any]:
        return self.api.df()

    def events(self) -> Stream:
        s = self.api.events(decode=True)
        return Stream(iter(s), s.close)

    # --- containers ----------------------------------------------------
    def containers(self) -> list[dict[str, Any]]:
        return self.api.containers(all=True)

    def start(self, cid: str) -> None:
        self.api.start(cid)

    def stop(self, cid: str) -> None:
        self.api.stop(cid)

    def restart(self, cid: str) -> None:
        self.api.restart(cid)

    def pause(self, cid: str) -> None:
        self.api.pause(cid)

    def unpause(self, cid: str) -> None:
        self.api.unpause(cid)

    def kill(self, cid: str) -> None:
        self.api.kill(cid)

    def remove_container(self, cid: str, force: bool = False) -> None:
        self.api.remove_container(cid, force=force)

    def prune_containers(self) -> dict[str, Any]:
        return self.api.prune_containers()

    def prune_builds(self) -> dict[str, Any]:
        return self.api.prune_builds(all=True)

    def stats_stream(self, cid: str) -> Iterator[dict[str, Any]]:
        return self.api.stats(cid, stream=True, decode=True)

    def logs(self, cid: str, tail: int = 500, timestamps: bool = False) -> Stream:
        s = self.api.logs(cid, stream=True, follow=True, tail=tail, timestamps=timestamps)

        def lines():
            buf = b""
            for chunk in s:
                buf += chunk
                *done, buf = buf.split(b"\n")
                for line in done:
                    yield line.decode("utf-8", "replace")
            if buf:
                yield buf.decode("utf-8", "replace")

        return Stream(lines(), s.close)

    def run(self, image: str, name: str | None, ports: dict[str, int], env: list[str]) -> str:
        c = self.client.containers.run(image, detach=True, name=name or None,
                                       ports=ports or None, environment=env or None)
        return c.name

    def inspect(self, kind: str, ident: str) -> dict[str, Any]:
        return {
            "container": self.api.inspect_container,
            "image": self.api.inspect_image,
            "volume": self.api.inspect_volume,
            "network": self.api.inspect_network,
        }[kind](ident)

    # --- images --------------------------------------------------------
    def images(self) -> list[dict[str, Any]]:
        return self.api.images(all=False)

    def remove_image(self, ref: str, force: bool = False) -> None:
        self.api.remove_image(ref, force=force)

    def pull(self, ref: str) -> Iterator[dict[str, Any]]:
        repo, _, tag = ref.rpartition(":") if ":" in ref.split("/")[-1] else (ref, "", "latest")
        return self.api.pull(repo, tag=tag or "latest", stream=True, decode=True)

    def prune_images(self, all_unused: bool) -> dict[str, Any]:
        return self.api.prune_images(filters={"dangling": not all_unused})

    # --- volumes -------------------------------------------------------
    def volumes(self) -> list[dict[str, Any]]:
        return self.api.volumes().get("Volumes") or []

    def remove_volume(self, name: str, force: bool = False) -> None:
        self.api.remove_volume(name, force=force)

    def prune_volumes(self, all_unused: bool, anonymous: list[str] | None = None) -> dict[str, Any]:
        """all_unused=False removes only anonymous volumes. Engines before 23.0 (API 1.42)
        have no such distinction — their prune deletes named volumes too — so there we
        remove the given anonymous volumes one by one instead."""
        if not all_unused and docker.utils.version_lt(self.api._version, "1.42"):
            deleted = []
            for name in anonymous or []:
                try:
                    self.api.remove_volume(name)
                    deleted.append(name)
                except DockerException:
                    pass  # in use by now, or already gone
            return {"VolumesDeleted": deleted, "SpaceReclaimed": 0}
        return self.api.prune_volumes(filters={"all": ["true"]} if all_unused else None)

    # --- networks ------------------------------------------------------
    def networks(self) -> list[dict[str, Any]]:
        return self.api.networks()

    def remove_network(self, nid: str) -> None:
        self.api.remove_network(nid)

    def prune_networks(self) -> dict[str, Any]:
        return self.api.prune_networks()

    # --- compose -------------------------------------------------------
    def compose_argv(self, p: ComposeProject, *args: str) -> list[str]:
        argv = ["docker", "compose", "-p", p.name]
        if p.working_dir:
            argv += ["--project-directory", p.working_dir]
        for f in p.config_files:
            argv += ["-f", f]
        return argv + list(args)

    def popen_lines(self, argv: list[str], cwd: str | None = None) -> Stream:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, cwd=cwd or None, env=self.cli_env(),
                                text=True, errors="replace", bufsize=1)

        def lines():
            assert proc.stdout
            for line in proc.stdout:
                yield line.rstrip("\n")
            rc = proc.wait()
            yield f"── exited with code {rc} ──"

        return Stream(lines(), proc.terminate)


__all__ = ["DockerService", "DockerException", "ComposeProject", "group_compose",
           "container_name", "Stream", "BUILTIN_NETWORKS", "COMPOSE_PROJECT", "COMPOSE_SERVICE"]
