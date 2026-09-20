"""Make ``app`` importable without relying on an exported PYTHONPATH.

Most test modules import ``app.agent...`` directly, which only resolves when
``backend`` happens to be on ``sys.path``.  Three modules worked around this
individually; doing it once here means running ``pytest backend/tests`` from
anywhere behaves the same as the documented command.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def pytest_configure(config):
    """Register the marker that separates runnable tests from frozen ones.

    The suite predates the instruction to verify with real material only, so
    most of it builds synthetic Cases and cannot be re-run as evidence.  Rather
    than delete that history, mark what is still runnable and select it:

        pytest backend/tests/agent -m real_data

    A module may carry ``real_data`` when it invents no Case, business owner or
    database identity -- either because it reads the repository's actual
    official material, or because it only exercises deterministic functions
    over literal inputs.  Passing it never means a real Case ran or was stored.
    """

    config.addinivalue_line(
        "markers",
        "real_data: creates no synthetic Case, business owner or DB identity",
    )
