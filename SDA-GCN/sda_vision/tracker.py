from scipy.spatial import distance
import numpy as np

class SimpleTracker:
    def __init__(self, max_disappeared=5, max_distance=300):
        self.next_object_id = 0
        self.objects = {} # dict[int, tuple[int, int]] -> id: (centroid_x, centroid_y)
        self.disappeared = {}
        self.max_disappeared = max_disappeared
        self.max_distance = max_distance

    def register(self, centroid):
        self.objects[self.next_object_id] = centroid
        self.disappeared[self.next_object_id] = 0
        self.next_object_id += 1
        return self.next_object_id - 1

    def deregister(self, object_id):
        del self.objects[object_id]
        del self.disappeared[object_id]

    def update(self, rects):
        if len(rects) == 0:
            for object_id in list(self.disappeared.keys()):
                self.disappeared[object_id] += 1
                if self.disappeared[object_id] > self.max_disappeared:
                    self.deregister(object_id)
            return {}

        input_centroids = np.zeros((len(rects), 2), dtype="int")
        for (i, (x_min, y_min, x_max, y_max)) in enumerate(rects):
            cX = int((x_min + x_max) / 2.0)
            cY = int((y_min + y_max) / 2.0)
            input_centroids[i] = (cX, cY)

        if len(self.objects) == 0:
            tracked_objects = {}
            for i in range(0, len(input_centroids)):
                obj_id = self.register(input_centroids[i])
                tracked_objects[obj_id] = i
            return tracked_objects

        object_ids = list(self.objects.keys())
        object_centroids = list(self.objects.values())

        D = distance.cdist(np.array(object_centroids), input_centroids)
        rows = D.min(axis=1).argsort()
        cols = D.argmin(axis=1)[rows]

        used_rows = set()
        used_cols = set()

        tracked_objects = {}

        for (row, col) in zip(rows, cols):
            if row in used_rows or col in used_cols:
                continue

            if D[row, col] > self.max_distance:
                continue

            object_id = object_ids[row]
            self.objects[object_id] = input_centroids[col]
            self.disappeared[object_id] = 0
            tracked_objects[object_id] = col

            used_rows.add(row)
            used_cols.add(col)

        unused_rows = set(range(0, D.shape[0])).difference(used_rows)
        unused_cols = set(range(0, D.shape[1])).difference(used_cols)

        for row in unused_rows:
            object_id = object_ids[row]
            self.disappeared[object_id] += 1
            if self.disappeared[object_id] > self.max_disappeared:
                self.deregister(object_id)

        for col in unused_cols:
            obj_id = self.register(input_centroids[col])
            tracked_objects[obj_id] = col

        return tracked_objects
