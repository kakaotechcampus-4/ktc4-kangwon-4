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
