"""Logging setup.

Everything is written to stderr: stdout is the MCP wire when the server runs
over the stdio transport, so a stray log record there would corrupt the session.
"""

import logging
import sys

_CONFIGURED = False


def configure_logging(level: str = "INFO") -> None:
    """Attach a single stderr handler to the root logger."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    numeric_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    root = logging.getLogger()
    root.setLevel(numeric_level)
    root.addHandler(handler)
    _CONFIGURED = True
