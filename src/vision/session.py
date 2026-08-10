from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class VisionSession:

    camera_id: str

    last_processed_frame_id: int = -1

    processed_frames: int = 0
    dropped_frames: int = 0

    state: dict[str, Any] = field(
        default_factory=dict
    )

    def note_frame(
        self,
        frame_id: int
    ):

        if self.last_processed_frame_id >= 0:

            gap = (
                frame_id
                - self.last_processed_frame_id
                - 1
            )

            if gap > 0:
                self.dropped_frames += gap

    def mark_processed(
        self,
        frame_id: int
    ):

        self.last_processed_frame_id = (
            frame_id
        )

        self.processed_frames += 1

    def get_buffer(
        self,
        name: str,
        maxlen: int
    ) -> deque:

        value = self.state.get(name)

        if value is None:

            value = deque(
                maxlen=maxlen
            )

            self.state[name] = value

            return value

        if not isinstance(value, deque):

            raise TypeError(
                f"{name} is not deque"
            )

        return value

    def reset(self):

        self.last_processed_frame_id = -1

        self.processed_frames = 0
        self.dropped_frames = 0

        self.state.clear()
