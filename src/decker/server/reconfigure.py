"""Who may change the server's settings from a client, and the exit code that asks the monitor for a restart."""

import ipaddress
import logging
import socket

RESTART_EXIT_CODE = 75


def _normalise(host: str) -> str | None:
    """Return the canonical IP text for a host string, mapping IPv4-in-IPv6 to IPv4, or None if it is not an IP."""
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return str(address)


def _is_loopback(host: str) -> bool:
    text = _normalise(host)
    return text is not None and ipaddress.ip_address(text).is_loopback


def _resolve(host: str) -> set[str]:
    literal = _normalise(host)
    if literal is not None:
        return {literal}
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        logging.warning("Cannot resolve %r for --allow-client-reconfiguration, ignoring it", host)
        return set()
    return {text for info in infos if (text := _normalise(str(info[4][0]))) is not None}


class ReconfigurePolicy:
    """Decides whether a connected client may change server settings."""

    def __init__(self, hosts: list[str] | None) -> None:
        """`None` denies everyone, `[]` allows any client, a list allows those hosts plus loopback."""
        self._enabled = hosts is not None
        self._any = hosts is not None and not hosts
        self._hosts: set[str] = set()
        for host in hosts or []:
            self._hosts |= _resolve(host)

    def allows(self, peer_host: str | None) -> bool:
        """Return True if a client connecting from `peer_host` may reconfigure the server."""
        if not self._enabled or peer_host is None:
            return False
        if self._any or _is_loopback(peer_host):
            return True
        return _normalise(peer_host) in self._hosts
