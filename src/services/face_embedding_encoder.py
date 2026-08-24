"""Application-facing face enrollment contract.

The Phase 3 implementation remains legacy InsightFace-backed. Phase 4 can
replace it without changing PersonService, API routes, or the database schema.
"""

from typing import Protocol, runtime_checkable

import numpy as np


class FaceEnrollmentError(ValueError):
    pass


@runtime_checkable
class FaceEmbeddingEncoder(Protocol):
    def extract(self, image_bytes: bytes) -> tuple[np.ndarray, float]:
        """Return a finite embedding and enrollment quality score."""
        ...
