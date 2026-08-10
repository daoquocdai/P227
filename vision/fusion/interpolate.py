import numpy as np

def interpolate_missing(kpts):
    """
    kpts: (T, V, 3)
    Nếu frame = 0 toàn bộ → nội suy từ frame lân cận
    """

    kpts = kpts.copy()
    T, V, C = kpts.shape

    for v in range(V):
        for c in range(C):
            seq = kpts[:, v, c]

            # Find non-zero positions
            nz = np.where(seq != 0)[0]

            if len(nz) == 0:
                continue  # leave zeros if no info

            # Fill missing at start
            first = nz[0]
            seq[:first] = seq[first]

            # Fill missing at end
            last = nz[-1]
            seq[last:] = seq[last]

            # Linear interpolate middle gaps
            for i in range(len(nz) - 1):
                start = nz[i]
                end = nz[i + 1]
                if end - start > 1:
                    seq[start:end] = np.linspace(seq[start], seq[end], end - start)

            kpts[:, v, c] = seq

    return kpts.astype(np.float32)
