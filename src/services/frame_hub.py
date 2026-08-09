import threading
import time

from src.models.frame import FramePacket


class FrameHub:
    """
    Multi-camera latest-frame hub.

    Mỗi camera giữ đúng 1 latest frame.
    Consumer chậm không làm producer bị block.
    """

    def __init__(self):
        self._condition = threading.Condition(
            threading.RLock()
        )

        self._frames: dict[str, FramePacket] = {}

        # Tăng mỗi khi bất kỳ camera nào publish frame.
        self._version = 0

    @property
    def version(self) -> int:
        with self._condition:
            return self._version

    def publish(self, packet: FramePacket):
        with self._condition:
            self._frames[packet.camera_id] = packet

            self._version += 1

            self._condition.notify_all()

    def get_latest(
        self,
        camera_id: str
    ) -> FramePacket | None:

        with self._condition:
            return self._frames.get(camera_id)

    def has_camera(self, camera_id: str) -> bool:
        with self._condition:
            return camera_id in self._frames

    def list_camera_ids(self) -> list[str]:
        with self._condition:
            return list(self._frames.keys())

    def remove(self, camera_id: str):
        with self._condition:
            self._frames.pop(camera_id, None)

            self._version += 1
            self._condition.notify_all()

    def wait_for_next(
        self,
        camera_id: str,
        after_frame_id: int = -1,
        timeout: float | None = 1.0,
    ) -> FramePacket | None:
        """
        Chờ frame mới hơn after_frame_id.

        Dùng cho MJPEG để không encode lặp cùng 1 frame.
        """

        deadline = (
            None
            if timeout is None
            else time.monotonic() + timeout
        )

        with self._condition:

            while True:

                packet = self._frames.get(camera_id)

                if (
                    packet is not None
                    and packet.frame_id > after_frame_id
                ):
                    return packet

                if deadline is None:
                    self._condition.wait()
                    continue

                remaining = deadline - time.monotonic()

                if remaining <= 0:
                    return None

                self._condition.wait(remaining)

    def wait_for_update(
        self,
        after_version: int,
        timeout: float = 0.5,
    ) -> int:
        """
        Chờ bất kỳ camera nào có frame mới.

        VisionWorker dùng cái này để tránh busy-loop.
        """

        deadline = time.monotonic() + timeout

        with self._condition:

            while self._version <= after_version:

                remaining = deadline - time.monotonic()

                if remaining <= 0:
                    return self._version

                self._condition.wait(remaining)

            return self._version
