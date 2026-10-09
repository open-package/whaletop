from __future__ import annotations

import argparse
import os
import sys

from . import __version__


def main() -> None:
    parser = argparse.ArgumentParser(prog="whaletop", description="htop-style terminal UI for Docker")
    parser.add_argument("-H", "--host", help="Docker daemon: unix:///path, tcp://host:port or "
                                             "ssh://[user@]host[:port] (default: DOCKER_HOST, then the "
                                             "current docker context)")
    parser.add_argument("-V", "--version", action="version", version=f"whaletop {__version__}")
    args = parser.parse_args()

    from .docker_client import DockerService

    try:
        svc = DockerService(args.host)
    except Exception as e:
        print(f"whaletop: cannot connect to the Docker daemon: {getattr(e, 'explanation', None) or e}",
              file=sys.stderr)
        if not (args.host or os.environ.get("DOCKER_HOST", "")).startswith(("ssh://", "tcp://")):
            print("Is Docker running, and can your user access its socket (docker group)?", file=sys.stderr)
        sys.exit(1)

    from .app import WhaletopApp

    try:
        WhaletopApp(svc).run()
    finally:
        svc.close()


if __name__ == "__main__":
    main()
