from whaletop import format as fmt
from whaletop.docker_client import group_compose
from whaletop.screens.dialogs import RunScreen
from whaletop.stats import compute

from .conftest import container, stats_frame


def test_human_size():
    assert fmt.human_size(0) == "0B"
    assert fmt.human_size(1536) == "1.5K"
    assert fmt.human_size(5 * 2**30) == "5.0G"
    assert fmt.human_size(None) == "-"


def test_cpu_percent_matches_docker_cli():
    # 100 ns of container time over 1000 ns of system time on 4 cpus = 40%
    assert round(fmt.cpu_percent(stats_frame(1000, 100000)), 6) == 40.0


def test_cpu_percent_first_frame_is_zero():
    assert fmt.cpu_percent({"cpu_stats": {"cpu_usage": {"total_usage": 5}}, "precpu_stats": {}}) == 0.0


def test_mem_usage_subtracts_inactive_file():
    used, limit = fmt.mem_usage(stats_frame(1, 1, mem=100))
    assert (used, limit) == (100, 1024 * 2**20)


def test_compute_rates():
    s1, io = compute(stats_frame(1000, 100000), None, now=10.0)
    assert s1.net_rx_rate == 0
    frame = stats_frame(2000, 200000)
    frame["networks"]["eth0"]["rx_bytes"] = 3000
    s2, _ = compute(frame, io, now=12.0)
    assert s2.net_rx_rate == 1000  # 2000 bytes over 2 seconds
    assert s2.pids == 3


def test_ports_dedup_ipv4_ipv6():
    ports = [{"PrivatePort": 80, "PublicPort": 8080, "Type": "tcp", "IP": "0.0.0.0"},
             {"PrivatePort": 80, "PublicPort": 8080, "Type": "tcp", "IP": "::"},
             {"PrivatePort": 53, "Type": "udp"}]
    host, ctr = fmt.ports_split(ports)
    assert host.plain == "8080, -"
    assert ctr.plain == "80/tcp, 53/udp"


def test_ports_split_shows_non_wildcard_host_ip():
    host, ctr = fmt.ports_split([{"PrivatePort": 5432, "PublicPort": 15432, "Type": "tcp", "IP": "127.0.0.1"}])
    assert (host.plain, ctr.plain) == ("127.0.0.1:15432", "5432/tcp")


def test_meter_has_requested_width():
    assert len(fmt.meter("CPU", 50, "50.0%", 40).plain) == 40


def test_strip_ansi():
    assert fmt.strip_ansi("\x1b[31mred\x1b[0m\r") == "red"


def test_group_compose():
    cs = [container("1", "a-web-1", project="a", service="web"),
          container("2", "a-db-1", project="a", service="db", state="exited"),
          container("3", "solo")]
    [p] = group_compose(cs)
    assert p.name == "a" and p.running == 1 and p.services == ["db", "web"]
    assert p.config_files == ["/nonexistent/compose.yaml"] and not p.files_exist


def test_parse_ports():
    assert RunScreen.parse_ports("8080:80, 5353:53/udp") == {"80/tcp": 8080, "53/udp": 5353}


def test_old_engine_anonymous_prune_never_touches_named_volumes():
    """Before API 1.42 a volume prune also deletes named volumes, so we remove one by one."""
    from types import SimpleNamespace

    from whaletop.docker_client import DockerService

    removed, pruned = [], []
    api = SimpleNamespace(_version="1.41", remove_volume=removed.append,
                          prune_volumes=lambda **kw: pruned.append(kw))
    svc = DockerService.__new__(DockerService)
    svc.api = api
    r = svc.prune_volumes(all_unused=False, anonymous=["anon1", "anon2"])
    assert removed == ["anon1", "anon2"] and not pruned and r["VolumesDeleted"] == ["anon1", "anon2"]
    api._version = "1.56"
    svc.prune_volumes(all_unused=False, anonymous=["anon1"])
    assert pruned == [{"filters": None}]


def test_ssh_tunnel_parses_docker_style_urls():
    import pytest

    from whaletop.docker_client import SSHTunnel

    t = SSHTunnel("ssh://deploy@prod-01:2222")
    assert (t.dest, t.port, t.remote) == ("deploy@prod-01", 2222, "/var/run/docker.sock")
    assert t._ssh("-O", "exit") == ["ssh", "-p", "2222", "-O", "exit", "deploy@prod-01"]
    t = SSHTunnel("ssh://prod-01")  # user and port come from ~/.ssh/config
    assert (t.dest, t.port) == ("prod-01", None)
    assert SSHTunnel("ssh://me@host/run/user/1000/docker.sock").remote == "/run/user/1000/docker.sock"
    with pytest.raises(ValueError):
        SSHTunnel("tcp://host:2375")
