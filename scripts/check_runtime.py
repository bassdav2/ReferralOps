from __future__ import annotations

import sys


def main() -> None:
    if sys.version_info < (3, 12):  # noqa: UP036 - runtime preflight intentionally checks old interpreters.
        version = ".".join(str(part) for part in sys.version_info[:3])
        raise SystemExit(
            f"Python 3.12 or newer is required for this demo. Detected Python {version}. "
            "Install Python 3.12 or run make bootstrap PYTHON=/path/to/python3.12."
        )
    print(f"Python runtime ok: {sys.version.split()[0]}")


if __name__ == "__main__":
    main()
