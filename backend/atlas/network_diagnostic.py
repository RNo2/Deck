"""Temporary Render startup probe: DNS/TCP only, no database login or TLS changes."""
import errno
import json
import os
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

CONNECT_TIMEOUT = 3
TOTAL_TIMEOUT = 25


def log(event, **fields):
    print(json.dumps({"diagnostic": "postgres_network", "event": event, **fields}), flush=True)


def target():
    """Never return/log the URL, username, password, database name or query."""
    parsed = urlsplit(os.environ.get("DATABASE_URL", ""))
    if parsed.scheme not in ("postgres", "postgresql", "postgresql+psycopg") or not parsed.hostname:
        raise ValueError("Invalid PostgreSQL target")
    port = parsed.port if parsed.port is not None else 5432
    if not 1 <= port <= 65535:
        raise ValueError("Invalid port")
    return parsed.hostname, port


def probe_family(host, port, family, label):
    try:
        addresses = sorted({entry[4] for entry in socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)})
    except socket.gaierror as exc:
        log("dns", family=label, status="failed", code=exc.errno)
        return
    log("dns", family=label, status="resolved", addresses=[address[0] for address in addresses])
    for address in addresses:
        try:
            with socket.socket(family, socket.SOCK_STREAM) as connection:
                connection.settimeout(CONNECT_TIMEOUT)
                connection.connect(address)
            log("tcp", family=label, address=address[0], port=port, status="reachable")
        except TimeoutError:
            log("tcp", family=label, address=address[0], port=port, status="timeout")
        except OSError as exc:
            log("tcp", family=label, address=address[0], port=port, status="failed",
                code=errno.errorcode.get(exc.errno, "OS_ERROR"))


def probe():
    try:
        host, port = target()
    except (ValueError, TypeError):
        log("target", status="invalid_database_url")
        return
    log("start", source="DATABASE_URL", port=port, tcp_timeout_seconds=CONNECT_TIMEOUT)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(probe_family, host, port, family, label)
                   for family, label in ((socket.AF_INET, "IPv4"), (socket.AF_INET6, "IPv6"))]
        for future in futures:
            future.result()
    log("complete", note="TCP reachability does not verify TLS or database authentication")


def main():
    # Bound DNS as well as connect calls. A stuck resolver cannot block startup indefinitely.
    # The child inherits DATABASE_URL; credentials never appear in process arguments.
    try:
        subprocess.run([sys.executable, "-m", "atlas.network_diagnostic", "--probe"],
                       timeout=TOTAL_TIMEOUT, check=False, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        log("timeout", timeout_seconds=TOTAL_TIMEOUT)
    except Exception:
        log("error", status="probe_unavailable")
    # Advisory only: leave migration/app success and failure behavior unchanged.


if __name__ == "__main__":
    if sys.argv[1:] == ["--probe"]:
        try:
            probe()
        except Exception:
            log("error", status="probe_failed")
    else:
        main()
