"""Make legacy standalone imports resolvable during repository-root collection."""

from __future__ import annotations

import sys
from pathlib import Path


SDA_GCN_ROOT = Path(__file__).resolve().parents[1]
if str(SDA_GCN_ROOT) not in sys.path:
    sys.path.insert(0, str(SDA_GCN_ROOT))
