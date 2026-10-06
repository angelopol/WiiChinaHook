"""Narrow interoperability fixes for the pinned Bumble release.

Observed on the user's clone: Configure Request option 80 02 20 03.
The high bit marks an optional hint. Bumble 0.0.235 rejects it as unknown,
and the peer never resends configuration, leaving HID setup stuck.
"""
from __future__ import annotations

import copy
import logging

log = logging.getLogger(__name__)


def normalize_configuration_options(options: bytes) -> bytes:
    result = bytearray()
    offset = 0
    # Options actually implemented by Bumble's ClassicChannel.
    supported = {1, 4, 5}
    while offset < len(options):
        if offset + 2 > len(options):
            raise ValueError("Truncated L2CAP configuration option header")
        kind, length = options[offset:offset + 2]
        end = offset + 2 + length
        if end > len(options):
            raise ValueError("Truncated L2CAP configuration option")
        if not kind & 0x80 or (kind & 0x7F) in supported:
            result.extend(bytes([kind & 0x7F, length]) + options[offset + 2:end])
        offset = end
    return bytes(result)


def install_l2cap_hint_compat(manager):
    original = manager.on_l2cap_configure_request
    def configure(connection, cid, request):
        try:
            options = normalize_configuration_options(request.options)
        except ValueError as exc:
            log.warning("Malformed L2CAP configuration: %s", exc)
            return
        if options != request.options:
            log.info("Ignoring optional L2CAP hint from %s", connection.peer_address)
            request = copy.copy(request)
            request.options = options
        original(connection, cid, request)
    manager.on_l2cap_configure_request = configure
