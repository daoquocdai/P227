import numpy as np

class Kalman1D:
    def __init__(self, R=0.01, Q=1e-5):
        # R: measurement noise
        # Q: process noise
        self.R = R
        self.Q = Q
        self.P = 1
        self.X = 0
        self.initialized = False

    def update(self, measurement):
        """One-dimensional Kalman update."""
        if not self.initialized:
            self.X = measurement
            self.initialized = True

        # Prediction
        self.P = self.P + self.Q

        # Kalman gain
        K = self.P / (self.P + self.R)

        # Correction
        self.X = self.X + K * (measurement - self.X)
        self.P = (1 - K) * self.P

        return self.X


def apply_kalman_filter(kpts):
    """
    kpts: numpy array (T, V, 3)
    Return smoothed keypoints
    """

    T, V, C = kpts.shape
    smoothed = np.zeros_like(kpts)

    # 46 joints × 3 channels → 138 Kalman filters
    filters = [[Kalman1D() for _ in range(C)] for _ in range(V)]

    for t in range(T):
        for v in range(V):
            for c in range(C):
                smoothed[t, v, c] = filters[v][c].update(kpts[t, v, c])

    return smoothed.astype(np.float32)
