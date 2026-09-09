"""Run the Web host for Cloudflare-exposed P2P play without Flask debug mode."""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

LAUNCH_ID_ENV = "FIVE_D_P2P_LAUNCH_ID"


def _load_port_utils():
    """Load the shared utility without importing the full Flask package.

    ``--select-port`` must write only its numeric result to stdout.  Loading
    ``src.web`` eagerly would also construct the application and its storage
    adapters before selection, which can emit unrelated startup warnings.
    """
    utility_path = PROJECT_ROOT / "src" / "web" / "port_utils.py"
    spec = importlib.util.spec_from_file_location(
        "five_d_chess_p2p_port_utils",
        utility_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load shared port utility: {utility_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_port_utils = _load_port_utils()
DEFAULT_HOST = _port_utils.DEFAULT_HOST
DEFAULT_PORT = _port_utils.DEFAULT_PORT
PortSelectionError = _port_utils.PortSelectionError
select_port = _port_utils.select_port
validate_port = _port_utils.validate_port
run_server = None


def _get_run_server():
    global run_server
    if run_server is None:
        from src.web import run_server as imported_run_server

        run_server = imported_run_server
    return run_server


def _parse_port(value: str) -> int:
    try:
        return validate_port(int(value))
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the 5D Chess P2P Web server")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument(
        "--port",
        type=_parse_port,
        help="strict server port; omit to select dynamically from the default window",
    )
    parser.add_argument(
        "--select-port",
        action="store_true",
        help="print one selected port as machine-readable stdout and exit",
    )
    args = parser.parse_args(argv)
    launch_id = os.environ.pop(LAUNCH_ID_ENV, None) or None

    if args.select_port:
        try:
            selected = select_port(
                host=args.host,
                preferred_port=(
                    DEFAULT_PORT if args.port is None else args.port
                ),
                quiet=True,
            )
        except PortSelectionError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(selected)
        return 0

    # An explicit P2P port is strict so the Cloudflare target and Flask bind
    # cannot silently diverge.  Omitting it keeps standalone P2P convenient:
    # the shared utility selects a free port and run_server logs its URL.
    _get_run_server()(
        host=args.host,
        port=DEFAULT_PORT if args.port is None else args.port,
        debug=False,
        strict_port=args.port is not None,
        launch_id=launch_id,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
