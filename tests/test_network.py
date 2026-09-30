import json
from unittest.mock import patch
import pytest
import tournament.network as network
from tournament.domain import RuleError


@pytest.mark.parametrize("base,expected", [
    ("http://localhost:8080/", "http://192.168.1.25:8080/"),
    ("http://127.0.0.1:8081/", "http://192.168.1.25:8081/"),
    ("http://[::1]:8080/", "http://192.168.1.25:8080/"),
    ("http://0.0.0.0:8080/", "http://192.168.1.25:8080/"),
    ("http://192.168.1.50:8080/", "http://192.168.1.50:8080/"),
])
def test_sharing_url_uses_network_address_and_correct_port(monkeypatch, base, expected):
    monkeypatch.delenv("TOURNAMENT_PUBLIC_URL", raising=False)
    monkeypatch.setattr(network, "discover_lan_ip", lambda: "192.168.1.25")
    assert network.sharing_url(base) == expected


def test_explicit_address_override(monkeypatch):
    monkeypatch.setenv("TOURNAMENT_PUBLIC_URL", "http://192.168.1.8:8082/")
    assert network.sharing_url("http://localhost:8080/") == "http://192.168.1.8:8082/"


def test_missing_network_does_not_generate_localhost_code(monkeypatch):
    monkeypatch.delenv("TOURNAMENT_PUBLIC_URL", raising=False)
    monkeypatch.setattr(network, "discover_lan_ip", lambda: None)
    with pytest.raises(RuleError, match="No local network"):
        network.sharing_url("http://localhost:8080/")


def test_discovery_prefers_physical_wifi_over_vpn(monkeypatch):
    def output(command, **kwargs):
        if "address" in command:
            return json.dumps([
                {"ifname":"lo", "addr_info":[{"scope":"host","local":"127.0.0.1"}]},
                {"ifname":"tailscale0", "addr_info":[{"scope":"global","local":"100.79.0.4"}]},
                {"ifname":"wlan0", "addr_info":[{"scope":"global","local":"192.168.1.25"}]},
                {"ifname":"docker0", "addr_info":[{"scope":"global","local":"172.17.0.1"}]},
            ])
        return json.dumps([{"dev":"tailscale0","metric":10},{"dev":"wlan0","metric":600}])
    monkeypatch.setattr(network.subprocess, "check_output", output)
    monkeypatch.setattr(network.Path, "exists", lambda path: str(path)=="/sys/class/net/wlan0/device")
    assert network.discover_lan_ip() == "192.168.1.25"


def test_wifi_without_internet_default_route(monkeypatch):
    def output(command, **kwargs):
        return json.dumps([{"ifname":"wlan0","addr_info":[{"scope":"global","local":"192.168.1.25"}]}] if "address" in command else [])
    monkeypatch.setattr(network.subprocess, "check_output", output)
    assert network.discover_lan_ip() == "192.168.1.25"


def test_qr_payload_and_displayed_link_match(app,monkeypatch):
    import tournament.app as app_module
    monkeypatch.delenv("TOURNAMENT_PUBLIC_URL", raising=False)
    monkeypatch.setattr(network, "discover_lan_ip", lambda: "192.168.1.25")
    client=app.test_client()
    expected="http://192.168.1.25:8080/"
    assert client.get("/api/share",base_url="http://localhost:8080").json["url"]==expected
    with patch.object(app_module.qrcode, "make", wraps=app_module.qrcode.make) as encode:
        response=client.get("/api/qr.svg",base_url="http://localhost:8080")
        assert response.status_code==200
        assert encode.call_args.args[0]==expected
        assert response.headers["Cache-Control"]=="no-store"
