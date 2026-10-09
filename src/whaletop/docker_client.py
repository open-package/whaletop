"""Thin wrapper over the docker SDK. The UI talks only to `DockerService`,
so tests can swap in a fake with the same methods."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
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


class SSHTunnel:
    """Forward a remote Docker socket to a local Unix socket with the system `ssh` client.

    docker-py's own ssh:// support needs paramiko, which has compiled dependencies; the
    system client also honours ~/.ssh/config, agents, jump hosts and password prompts.
    One multiplexed connection is kept open until close().

    ssh://user@host[:port] forwards /var/run/docker.sock; a path selects another socket,
    e.g. ssh://user@host/run/user/1000/docker.sock for rootless Docker.
    """

    DEFAULT_SOCKET = "/var/run/docker.sock"

    def __init__(self, url: str):
        u = urlsplit(url)
        if u.scheme != "ssh" or not u.hostname:
            raise ValueError(f"not an ssh:// URL: {url}")
        self.url = url
        self.dest = f"{u.username}@{u.hostname}" if u.username else u.hostname
        self.port = u.port
        self.remote = u.path if u.path not in ("", "/") else self.DEFAULT_SOCKET
        self._dir: str | None = None

    @property
    def local(self) -> str:
        assert self._dir
        return os.path.join(self._dir, "docker.sock")

    def _ssh(self, *args: str) -> list[str]:
        return ["ssh", *(["-p", str(self.port)] if self.port else []), *args, self.dest]

    def open(self, timeout: float = 30.0) -> str:
        """Connect (prompting on the terminal if needed); returns unix:// URL of the forward."""
        if not shutil.which("ssh"):
            raise DockerException("ssh:// hosts need the OpenSSH client (ssh) on PATH")
        self._dir = tempfile.mkdtemp(prefix="whaletop-ssh-")
        argv = self._ssh("-f", "-N", "-M", "-S", os.path.join(self._dir, "ctl"),
                         "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=30",
                         "-L", f"{self.local}:{self.remote}")
        if subprocess.run(argv).returncode != 0:  # -f: returns once the forward is up
            self.close()
            raise DockerException(f"ssh connection to {self.dest} failed")
        deadline = time.monotonic() + timeout
        while not os.path.exists(self.local):
            if time.monotonic() > deadline:
                self.close()
                raise DockerException(f"ssh forward to {self.dest}:{self.remote} did not come up")
            time.sleep(0.05)
        return f"unix://{self.local}"

    def close(self) -> None:
        if not self._dir:
            return
        subprocess.run(self._ssh("-S", os.path.join(self._dir, "ctl"), "-O", "exit"),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(self._dir, ignore_errors=True)
        self._dir = None


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
        """Daemon selection, in order: `host` (--host), DOCKER_HOST (with DOCKER_TLS_VERIFY /
        DOCKER_CERT_PATH), the docker CLI's current context (with its TLS settings), then
        the default local socket. ssh:// addresses go through an SSHTunnel."""
        self.tunnel: SSHTunnel | None = None
        self.cli_host: str | None = None  # DOCKER_HOST for docker CLI subprocesses
        kw: dict[str, Any] = {"max_pool_size": 64}
        ctx = None
        if not host and not os.environ.get("DOCKER_HOST"):
            try:
                from docker.context import ContextAPI

                ctx = ContextAPI.get_current_context()
            except Exception:
                ctx = None
        target = host or os.environ.get("DOCKER_HOST") or (ctx.Host if ctx and ctx.Host else None)
        self.host = target  # for display
        try:
            if target and target.startswith("ssh://"):
                self.tunnel = SSHTunnel(target)
                local = self.tunnel.open()
                self.client = docker.DockerClient(base_url=local, **kw)
                self.cli_host = local  # reuse the tunnel: no second login for exec/compose
            elif host:
                self.client = docker.DockerClient(base_url=host, **kw)
                self.cli_host = host
            elif os.environ.get("DOCKER_HOST"):
                self.client = docker.from_env(**kw)  # honours the TLS environment variables
            elif ctx and ctx.Host:
                self.client = docker.DockerClient(base_url=ctx.Host, tls=ctx.TLSConfig or False, **kw)
            else:
                self.client = docker.from_env(**kw)
            self.api = self.client.api
            self.api.ping()
        except Exception as e:
            tunnel = self.tunnel
            self.close()
            if tunnel:  # ssh itself succeeded, so the failure is on the remote side
                raise DockerException(
                    f"connected to {tunnel.dest} over SSH, but the Docker socket {tunnel.remote} could "
                    "not be reached through it. The SSH server must allow forwarding "
                    "(AllowTcpForwarding / AllowStreamLocalForwarding in sshd_config) and the remote "
                    "user needs access to the socket (docker group).") from e
            raise

    def close(self) -> None:
        if self.tunnel:
            self.tunnel.close()
            self.tunnel = None

    # env for docker CLI subprocesses so they talk to the same daemon
    def cli_env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.cli_host:
            env["DOCKER_HOST"] = self.cli_host
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
