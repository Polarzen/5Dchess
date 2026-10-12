"""Bounded local TCP port selection for the Web launchers.

Port selection is deliberately kept outside Flask so the normal Web entry
point and the P2P launcher share one probe implementation.  A selected port
is only a best-effort reservation: the final server bind can still lose a
race to another process, and callers must report that failure clearly.
"""
from __future__ import annotations

import socket
import logging
from typing import Callable


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5050
PORT_SEARCH_SIZE = 50
MAX_PORT = 65535
DEFAULT_PORT_START = DEFAULT_PORT
DEFAULT_PORT_END = min(DEFAULT_PORT + PORT_SEARCH_SIZE - 1, MAX_PORT)
MAX_PORT_CANDIDATES = PORT_SEARCH_SIZE


class PortSelectionError(RuntimeError):
    """Raised when no candidate port in the bounded search window is free."""


def _validate_port(port: int, *, name: str = "port") -> int:
    if isinstance(port, bool) or not isinstance(port, int):
        raise ValueError(f"{name} must be an integer from 1 to {MAX_PORT}")
    if not 1 <= port <= MAX_PORT:
        raise ValueError(f"{name} must be an integer from 1 to {MAX_PORT}")
    return port


def validate_port(port: int, *, name: str = "port") -> int:
    """Validate a caller-supplied port without probing or reserving it."""
    return _validate_port(port, name=name)


def is_port_available(host: str, port: int) -> bool:
    """Return whether ``host:port`` can be bound by a TCP listener.

    The probe always owns and closes its socket, including when Windows or
    another platform reports an access-denied/in-use ``OSError``.
    """
    _validate_port(port)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((host, port))
        return True
    except OSError:
        return False


def select_port(
    host: str = DEFAULT_HOST,
    preferred_port: int = DEFAULT_PORT,
    *,
    max_candidates: int = PORT_SEARCH_SIZE,
    log: Callable[[str], None] | None = None,
    quiet: bool = False,
) -> int:
    """Select the first bindable port in an ascending bounded window.

    ``preferred_port`` is the first candidate, not a strict request.  At most
    ``max_candidates`` ports are checked and the range is clamped at 65535.
    Skipped candidates emit concise INFO messages by default.  Passing ``log``
    replaces that logger callback; machine-readable callers set ``quiet`` to
    keep stdout numeric-only.
    """
    preferred_port = _validate_port(preferred_port, name="preferred_port")
    if (
        isinstance(max_candidates, bool)
        or not isinstance(max_candidates, int)
        or max_candidates < 1
    ):
        raise ValueError("max_candidates must be a positive integer")

    end_port = min(preferred_port + max_candidates - 1, MAX_PORT)
    if log is None and not quiet:
        log = logging.getLogger("chess_5d").info
    for port in range(preferred_port, end_port + 1):
        if is_port_available(host, port):
            return port
        if log is not None:
            log(f"Web port {port} unavailable; trying next")

    raise PortSelectionError(
        f"No available Web port in searched range {preferred_port}-{end_port}"
    )


# Descriptive alias for callers that prefer the operation-oriented name.
find_available_port = select_port
select_available_port = select_port
