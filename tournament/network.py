"""Resolve a phone-accessible address without sending traffic to the internet."""

import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
from urllib.parse import urlsplit, urlunsplit

from .domain import RuleError


def usable_ipv4(value):
    try:
        address = ipaddress.IPv4Address(value)
        return not (address.is_loopback or address.is_unspecified or
                    address.is_link_local or address.is_multicast)
    except ipaddress.AddressValueError:
        return False


def discover_lan_ip():
    try:
        addresses = json.loads(subprocess.check_output(
            ["ip", "-j", "-4", "address", "show", "up"], timeout=2, stderr=subprocess.DEVNULL))
        candidates = [
            (interface["ifname"], entry["local"])
            for interface in addresses
            for entry in interface.get("addr_info", [])
            if entry.get("scope") == "global" and usable_ipv4(entry.get("local", ""))
        ]
        # Prefer a physical Wi-Fi/Ethernet interface over VPN and container interfaces.
        physical = [item for item in candidates if (Path("/sys/class/net") / item[0] / "device").exists()]
        candidates = physical or candidates
        try:
            routes = json.loads(subprocess.check_output(
                ["ip", "-j", "-4", "route", "show", "default"], timeout=2, stderr=subprocess.DEVNULL))
        except (OSError, subprocess.SubprocessError, ValueError):
            routes = []
        for route in sorted(routes, key=lambda r: r.get("metric", 0)):
            match = next((address for interface, address in candidates if interface == route.get("dev")), None)
            if match:
                return match
        if candidates:
            return candidates[0][1]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        pass
    # Fallback for systems without iproute2; this only resolves the local hostname.
    try:
        for entry in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            if usable_ipv4(entry[4][0]):
                return entry[4][0]
    except OSError:
        pass
    return None


def sharing_url(base_url):
    override = os.environ.get("TOURNAMENT_PUBLIC_URL")
    if override:
        parsed = urlsplit(override)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise RuleError("TOURNAMENT_PUBLIC_URL must be a complete http:// or https:// address.")
        return override
    parsed = urlsplit(base_url)
    # Preserve a network IP already used by the visitor; localhost needs discovery.
    address = parsed.hostname if usable_ipv4(parsed.hostname or "") else discover_lan_ip()
    if not address:
        raise RuleError("No local network address was found. Connect the host to Wi-Fi or set TOURNAMENT_PUBLIC_URL to its network URL.")
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit((parsed.scheme, address + port, "/", "", ""))
