"""Small keypoint cleaning utilities shared by offline and realtime paths."""

import numpy as np


def clean_out_of_bounds_data(data):
    """Clamp normalized X/Y coordinates while leaving depth unchanged."""
    clean_data = data.copy()
    clean_data[:, :, 0] = np.clip(clean_data[:, :, 0], 0.0, 1.0)
    clean_data[:, :, 1] = np.clip(clean_data[:, :, 1], 0.0, 1.0)
    return clean_data
