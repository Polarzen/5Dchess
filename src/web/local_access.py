"""Host-only operations must also reject loopback Cloudflare proxy traffic."""
import ipaddress

from flask import request


def is_local_host():
    try:
        loopback = ipaddress.ip_address(request.remote_addr or "").is_loopback
    except ValueError:
        return False
    hostname = request.host.split(":")[0].lower()
    if request.host.startswith("["):
        hostname = request.host.split("]")[0] + "]"
    return (loopback and hostname in {"localhost", "127.0.0.1", "[::1]"}
            and not any(name.lower().startswith(("x-forwarded-", "cf-"))
                        or name.lower() == "forwarded" for name in request.headers.keys())
            and request.headers.get("Sec-Fetch-Site") not in {"cross-site", "same-site"}
            and request.headers.get("Origin", request.host_url.rstrip("/"))
            == request.host_url.rstrip("/"))
