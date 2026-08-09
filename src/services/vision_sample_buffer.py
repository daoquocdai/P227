import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field, replace

from src.models.frame import FramePacket


@dataclass
class _CameraTemporalState:
    enabled: bool = False
    packets: deque[FramePacket] = field(default_factory=deque)
    source_epoch: int | None = None
    source_time_kind: str | None = None
    next_input_timestamp: float | None = None
    temporal_drop_count: int = 0
    input_drop_count: int = 0
    overload_count: int = 0
    epoch_temporal_drop_count: int = 0
    epoch_input_drop_count: int = 0
    epoch_overload_count: int = 0
    degraded_reason: str | None = None
    last_discontinuity: dict | None = None
    service_started_at: float | None = None
    service_last_at: float | None = None
    processed_count: int = 0
    sampled_count: int = 0
    first_sample_timestamp: float | None = None
    last_sample_timestamp: float | None = None
    window_source_time_span: float | None = None
    strict_window_observed: bool = False


class VisionSampleBuffer:
    """Bounded source-time sampler dedicated to Vision consumption.

    Legacy V1 samples every other engine input. The public target rate is the
    actual model-observation cadence, while the input grid is faster by the
    explicit skip factor. Queue eviction always preserves that pairing.
    """

    def __init__(
        self,
        *,
        target_sample_rate: float = 15.0,
        legacy_skip_factor: int = 2,
        capacity: int = 8,
    ) -> None:
        if target_sample_rate <= 0:
            raise ValueError("target_sample_rate must be positive")
        if legacy_skip_factor < 1:
            raise ValueError("legacy_skip_factor must be positive")
        if capacity < legacy_skip_factor or capacity % legacy_skip_factor:
            raise ValueError("capacity must be a positive multiple of legacy_skip_factor")
        self.target_sample_rate = target_sample_rate
        self.legacy_skip_factor = legacy_skip_factor
        self.capacity = capacity
        self.input_rate = target_sample_rate * legacy_skip_factor
        self._input_period = 1.0 / self.input_rate
        self._condition = threading.Condition(threading.RLock())
        self._states: dict[str, _CameraTemporalState] = {}
        self._version = 0

    @property
    def version(self) -> int:
        with self._condition:
            return self._version

    def enable(self, camera_id: str) -> None:
        with self._condition:
            state = self._states.setdefault(camera_id, _CameraTemporalState())
            self._reset_state(state)
            state.enabled = True
            self._notify()

    def disable(self, camera_id: str) -> None:
        with self._condition:
            state = self._states.setdefault(camera_id, _CameraTemporalState())
            self._reset_state(state)
            state.enabled = False
            self._notify()

    def clear(self, camera_id: str, reason: str = "source_stopped") -> None:
        with self._condition:
            state = self._states.get(camera_id)
            if state is None:
                return
            was_enabled = state.enabled
            self._reset_state(state)
            state.enabled = was_enabled
            state.last_discontinuity = {"reason": reason, "observed_at": time.time()}
            self._notify()

    def offer(self, packet: FramePacket) -> bool:
        """Offer without waiting; returns whether this packet entered the buffer."""
        with self._condition:
            state = self._states.setdefault(packet.camera_id, _CameraTemporalState())
            if not state.enabled:
                return False
            source_timestamp = self._source_timestamp(packet)
            explicit_discontinuity = packet.discontinuity
            epoch_changed = state.source_epoch is not None and packet.source_epoch != state.source_epoch
            rolled_back = (
                state.next_input_timestamp is not None
                and source_timestamp + self._input_period < state.next_input_timestamp - self._input_period
            )
            major_gap = (
                state.next_input_timestamp is not None
                and source_timestamp - state.next_input_timestamp > 63.0 / self.target_sample_rate
            )
            if packet.discontinuity or epoch_changed or rolled_back or major_gap:
                if (rolled_back or major_gap) and not packet.discontinuity:
                    packet = replace(packet, discontinuity=True)
                self._reset_epoch(
                    state,
                    source_epoch=packet.source_epoch,
                    source_timestamp=source_timestamp,
                    reason=(
                        "packet_discontinuity"
                        if explicit_discontinuity
                        else "source_epoch_changed"
                        if epoch_changed
                        else "timestamp_rollback"
                        if rolled_back
                        else "major_source_gap"
                        if major_gap
                        else "source_discontinuity"
                    ),
                )
            elif state.source_epoch is None:
                state.source_epoch = packet.source_epoch
            state.source_time_kind = packet.source_time_kind

            if state.next_input_timestamp is None:
                state.next_input_timestamp = source_timestamp

            tolerance = self._input_period * 0.25
            if source_timestamp + tolerance < state.next_input_timestamp:
                return False

            overdue = source_timestamp - state.next_input_timestamp
            missed_slots = max(0, math.floor((overdue + tolerance) / self._input_period))
            if missed_slots:
                state.input_drop_count += missed_slots
                state.temporal_drop_count += math.ceil(missed_slots / self.legacy_skip_factor)
                state.epoch_input_drop_count += missed_slots
                state.epoch_temporal_drop_count += math.ceil(missed_slots / self.legacy_skip_factor)
                state.degraded_reason = "source_cadence_gap"
                state.next_input_timestamp += missed_slots * self._input_period

            if len(state.packets) >= self.capacity:
                drop_count = min(self.legacy_skip_factor, len(state.packets))
                for _ in range(drop_count):
                    state.packets.popleft()
                state.input_drop_count += drop_count
                state.temporal_drop_count += math.ceil(drop_count / self.legacy_skip_factor)
                state.overload_count += 1
                state.epoch_input_drop_count += drop_count
                state.epoch_temporal_drop_count += math.ceil(drop_count / self.legacy_skip_factor)
                state.epoch_overload_count += 1
                state.degraded_reason = "buffer_overload"

            state.packets.append(packet)
            state.next_input_timestamp += self._input_period
            self._notify()
            return True

    def get_nowait(self, camera_id: str) -> FramePacket | None:
        with self._condition:
            state = self._states.get(camera_id)
            if state is None or not state.enabled or not state.packets:
                return None
            packet = state.packets.popleft()
            self._notify()
            return packet

    def wait_for_update(self, after_version: int, timeout: float = 0.5) -> int:
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._version <= after_version:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            return self._version

    def note_result(self, packet: FramePacket, metadata: dict) -> None:
        with self._condition:
            state = self._states.get(packet.camera_id)
            if state is None or not state.enabled:
                return
            now = time.monotonic()
            if state.service_started_at is None:
                state.service_started_at = now
            state.service_last_at = now
            state.processed_count += 1
            if metadata.get("sampled"):
                source_timestamp = self._source_timestamp(packet)
                state.sampled_count += 1
                if state.first_sample_timestamp is None:
                    state.first_sample_timestamp = source_timestamp
                state.last_sample_timestamp = source_timestamp
            span = metadata.get("window_source_time_span")
            if span is not None:
                state.window_source_time_span = float(span)
                expected_span = 63.0 / self.target_sample_rate
                state.strict_window_observed = abs(float(span) - expected_span) <= self._input_period
                if not state.strict_window_observed and state.degraded_reason is None:
                    state.degraded_reason = "window_source_span"

    def get_status(self, camera_id: str) -> dict:
        with self._condition:
            state = self._states.get(camera_id)
            if state is None or not state.enabled:
                return self._unavailable_status()
            service_duration = (
                0.0
                if state.service_started_at is None or state.service_last_at is None
                else state.service_last_at - state.service_started_at
            )
            service_rate = (
                (state.sampled_count - 1) / service_duration
                if state.sampled_count > 1 and service_duration > 0
                else 0.0
            )
            source_duration = (
                0.0
                if state.first_sample_timestamp is None or state.last_sample_timestamp is None
                else state.last_sample_timestamp - state.first_sample_timestamp
            )
            effective_rate = (
                (state.sampled_count - 1) / source_duration
                if state.sampled_count > 1 and source_duration > 0
                else 0.0
            )
            degraded = (
                state.epoch_temporal_drop_count > 0
                or state.epoch_overload_count > 0
                or bool(state.degraded_reason)
            )
            if degraded:
                fidelity = "degraded"
            elif state.strict_window_observed:
                fidelity = "strict"
            else:
                fidelity = "unavailable"
            return {
                "target_sample_rate": self.target_sample_rate,
                "target_input_rate": self.input_rate,
                "effective_sample_rate": effective_rate,
                "service_rate": service_rate,
                "buffer_depth": len(state.packets),
                "buffer_capacity": self.capacity,
                "temporal_drop_count": state.temporal_drop_count,
                "input_drop_count": state.input_drop_count,
                "overload_count": state.overload_count,
                "epoch_temporal_drop_count": state.epoch_temporal_drop_count,
                "epoch_input_drop_count": state.epoch_input_drop_count,
                "epoch_overload_count": state.epoch_overload_count,
                "window_source_time_span": state.window_source_time_span,
                "temporal_fidelity": fidelity,
                "degraded_reason": state.degraded_reason,
                "last_discontinuity": state.last_discontinuity,
                "source_epoch": state.source_epoch,
                "source_time_kind": state.source_time_kind,
            }

    def _unavailable_status(self) -> dict:
        return {
            "target_sample_rate": self.target_sample_rate,
            "target_input_rate": self.input_rate,
            "effective_sample_rate": 0.0,
            "service_rate": 0.0,
            "buffer_depth": 0,
            "buffer_capacity": self.capacity,
            "temporal_drop_count": 0,
            "input_drop_count": 0,
            "overload_count": 0,
            "epoch_temporal_drop_count": 0,
            "epoch_input_drop_count": 0,
            "epoch_overload_count": 0,
            "window_source_time_span": None,
            "temporal_fidelity": "unavailable",
            "degraded_reason": "temporal_sampling_disabled",
            "last_discontinuity": None,
            "source_epoch": None,
            "source_time_kind": None,
        }

    def _reset_epoch(
        self,
        state: _CameraTemporalState,
        *,
        source_epoch: int,
        source_timestamp: float,
        reason: str,
    ) -> None:
        state.packets.clear()
        state.source_epoch = source_epoch
        state.source_time_kind = None
        state.next_input_timestamp = source_timestamp
        state.service_started_at = None
        state.service_last_at = None
        state.processed_count = 0
        state.sampled_count = 0
        state.first_sample_timestamp = None
        state.last_sample_timestamp = None
        state.window_source_time_span = None
        state.strict_window_observed = False
        state.epoch_temporal_drop_count = 0
        state.epoch_input_drop_count = 0
        state.epoch_overload_count = 0
        state.degraded_reason = None
        state.last_discontinuity = {
            "reason": reason,
            "source_epoch": source_epoch,
            "source_timestamp": source_timestamp,
            "observed_at": time.time(),
        }

    @staticmethod
    def _reset_state(state: _CameraTemporalState) -> None:
        state.packets.clear()
        state.source_epoch = None
        state.source_time_kind = None
        state.next_input_timestamp = None
        state.temporal_drop_count = 0
        state.input_drop_count = 0
        state.overload_count = 0
        state.epoch_temporal_drop_count = 0
        state.epoch_input_drop_count = 0
        state.epoch_overload_count = 0
        state.degraded_reason = None
        state.last_discontinuity = None
        state.service_started_at = None
        state.service_last_at = None
        state.processed_count = 0
        state.sampled_count = 0
        state.first_sample_timestamp = None
        state.last_sample_timestamp = None
        state.window_source_time_span = None
        state.strict_window_observed = False

    @staticmethod
    def _source_timestamp(packet: FramePacket) -> float:
        return packet.captured_at if packet.source_timestamp is None else packet.source_timestamp

    def _notify(self) -> None:
        self._version += 1
        self._condition.notify_all()
