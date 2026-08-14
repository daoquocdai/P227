import json
import time

import numpy as np

from src.database import database_connection
from src.models.frame import FramePacket
from src.models.vision import VisionDetection, VisionEvent, VisionResult
from src.services import event_snapshot
from src.services.camera_service import camera_service
from src.services.event_service import EventService
from src.services.sqlite_event_repository import stable_uuid
from src.services.vision_event_dispatcher import VisionEventAdapter
from src.services.vision_product_policy import VisionProductPolicy


def result(*, confidence=0.9, similarity=0.1, state="LOCKED_UNKNOWN"):
    return VisionResult(
        camera_id="policy-camera",
        frame_id=12,
        captured_at=time.time(),
        processed_at=time.time(),
        processing_ms=1.0,
        detections=[
            VisionDetection(
                "person",
                0.95,
                (1, 1, 8, 8),
                7,
                {
                    "identity_status": "UNKNOWN",
                    "identity_similarity": similarity,
                    "identity_state": state,
                    "identity_face_detected": True,
                },
            )
        ],
        events=[VisionEvent("fall_confirmed", confidence, {"event_id": "policy-fall"})],
        metadata={"sampled": True},
    )


def set_thresholds(stranger, fall):
    with database_connection() as connection:
        row = connection.execute(
            "SELECT value_json FROM system_settings WHERE setting_key = 'general'"
        ).fetchone()
        values = json.loads(row["value_json"])
        values.update(stranger_threshold=stranger, fall_threshold=fall)
        connection.execute(
            "UPDATE system_settings SET value_json = ? WHERE setting_key = 'general'",
            (json.dumps(values),),
        )


def test_product_thresholds_gate_below_and_accept_equal_confidence():
    set_thresholds(stranger=80, fall=80)
    below = VisionProductPolicy().apply(result(confidence=0.79, similarity=0.21))
    assert below.events == []

    equal = VisionProductPolicy().apply(result(confidence=0.80, similarity=0.20))
    assert {event.type for event in equal.events} == {"fall_confirmed", "unknown_person"}


def test_unknown_requires_final_retry_state_and_has_cooldown():
    set_thresholds(stranger=78, fall=72)
    now = [100.0]
    policy = VisionProductPolicy(unknown_cooldown_seconds=30, clock=lambda: now[0])
    assert not any(event.type == "unknown_person" for event in policy.apply(result(state="PENDING")).events)
    assert sum(event.type == "unknown_person" for event in policy.apply(result()).events) == 1
    assert not any(event.type == "unknown_person" for event in policy.apply(result()).events)
    now[0] += 30
    assert sum(event.type == "unknown_person" for event in policy.apply(result()).events) == 1

    different_track = result()
    different_track.detections[0].track_id = 8
    assert sum(event.type == "unknown_person" for event in policy.apply(different_track).events) == 1


def test_feature_boundary_clears_unknown_cooldown_for_a_fresh_workflow():
    set_thresholds(stranger=78, fall=72)
    policy = VisionProductPolicy(unknown_cooldown_seconds=30, clock=lambda: 100.0)
    first = result()
    policy.apply(first)
    suppressed = result()
    policy.apply(suppressed)
    assert sum(event.type == "unknown_person" for event in first.events) == 1
    assert not any(event.type == "unknown_person" for event in suppressed.events)

    policy.clear_camera("policy-camera")
    fresh = result()
    policy.apply(fresh)
    assert sum(event.type == "unknown_person" for event in fresh.events) == 1


def test_default_cooldown_uses_observation_time_not_processing_wall_clock():
    set_thresholds(stranger=78, fall=72)
    policy = VisionProductPolicy(unknown_cooldown_seconds=30)
    first = result()
    first.metadata.update(observation_time=10.0, source_epoch=2)
    policy.apply(first)
    within = result()
    within.metadata.update(observation_time=39.9, source_epoch=2)
    policy.apply(within)
    after = result()
    after.metadata.update(observation_time=40.0, source_epoch=2)
    policy.apply(after)

    assert sum(event.type == "unknown_person" for event in first.events) == 1
    assert not any(event.type == "unknown_person" for event in within.events)
    assert sum(event.type == "unknown_person" for event in after.events) == 1


def test_known_identity_never_creates_unknown_person_event():
    set_thresholds(stranger=50, fall=70)
    known = result(confidence=0.0)
    known.events.clear()
    known.detections[0].metadata = {
        "identity_status": "KNOWN",
        "identity_state": "RECOGNIZED",
        "identity_face_detected": True,
        "identity_similarity": 0.91,
        "identity_name": "An",
        "identity_person_id": "person-an",
    }

    VisionProductPolicy().apply(known)

    assert known.events == []
    assert known.detections[0].metadata["identity_name"] == "An"


def test_identity_disabled_metadata_cannot_create_unknown_event():
    disabled = result()
    disabled.events.clear()
    disabled.detections[0].metadata = {}
    VisionProductPolicy().apply(disabled)
    assert disabled.events == []


def test_exact_frame_snapshot_reaches_database_and_unknown_is_blurred(tmp_path, monkeypatch):
    monkeypatch.setattr(event_snapshot, "SNAPSHOT_ROOT", tmp_path)
    monkeypatch.setattr("src.services.media_paths.SNAPSHOT_ROOT", tmp_path)
    vision_result = result()
    vision_result.metadata["geometry"] = {"scale": 1.0, "pad_x": 0, "pad_y": 0}
    vision_result.detections[0].metadata.update(
        identity_face_bbox_xyxy=[1, 1, 5, 5],
        identity_face_bbox_frame_id=vision_result.frame_id,
    )
    VisionProductPolicy().apply(vision_result)
    packet = FramePacket(
        "policy-camera",
        12,
        vision_result.captured_at,
        np.indices((24, 24)).sum(axis=0).astype(np.uint8)[..., None].repeat(3, axis=2) * 10,
        vision_result=vision_result,
    )
    event_snapshot.attach_event_snapshots(packet, vision_result)

    fall = next(event for event in vision_result.events if event.type == "fall_confirmed")
    unknown = next(event for event in vision_result.events if event.type == "unknown_person")
    assert (tmp_path / fall.metadata["snapshot_path"]).is_file()
    assert (tmp_path / unknown.metadata["snapshot_path"]).is_file()
    assert unknown.metadata["snapshot_blurred"] is True
    assert fall.metadata["snapshot_blurred"] is True

    service = EventService()
    import asyncio

    asyncio.run(service.create(VisionEventAdapter().adapt(vision_result)[0]))
    asyncio.run(service.create(VisionEventAdapter().adapt(vision_result)[1]))
    alerts = asyncio.run(service.list_alerts())
    with database_connection() as connection:
        fall_media = connection.execute(
            "SELECT subject_type, relative_path FROM media_assets WHERE event_id = ?",
            (stable_uuid(fall.metadata["event_id"], "event"),),
        ).fetchone()
        unknown_media = connection.execute(
            "SELECT subject_type, is_blurred, relative_path FROM media_assets WHERE event_id = ?",
            (stable_uuid(unknown.metadata["event_id"], "event"),),
        ).fetchone()
    assert tuple(fall_media) == ("fall", fall.metadata["snapshot_path"])
    assert tuple(unknown_media) == ("unknown_person", 1, unknown.metadata["snapshot_path"])
    snapshot_urls = {alert["snapshot_url"] for alert in alerts if alert["event_id"] in {"policy-fall", unknown.metadata["event_id"]}}
    assert snapshot_urls == {
        f"/snapshots/{fall.metadata['snapshot_path']}",
        f"/snapshots/{unknown.metadata['snapshot_path']}",
    }


def test_blur_faces_changes_only_clipped_valid_face_rois():
    frame = np.indices((20, 20)).sum(axis=0).astype(np.uint8)[..., None].repeat(3, axis=2) * 8
    output, count = event_snapshot.blur_faces(
        frame,
        [(-3, -2, 8, 9), (5, 5, 5, 9), (8, 8, 12, 8), None, (30, 30, 40, 40)],
    )
    assert count == 1
    assert np.any(output[:9, :8] != frame[:9, :8])
    assert np.array_equal(output[10:, 10:], frame[10:, 10:])
    assert np.array_equal(frame[10:, 10:], np.indices((20, 20)).sum(axis=0).astype(np.uint8)[10:, 10:, None].repeat(3, axis=2) * 8)


def test_snapshot_ignores_face_bbox_from_a_different_frame(tmp_path, monkeypatch):
    monkeypatch.setattr(event_snapshot, "SNAPSHOT_ROOT", tmp_path)
    vision_result = result()
    vision_result.events = [VisionEvent("fall_confirmed", 0.9, {})]
    vision_result.detections[0].metadata.update(
        identity_face_bbox_xyxy=[1, 1, 5, 5],
        identity_face_bbox_frame_id=vision_result.frame_id - 1,
    )
    packet = FramePacket(
        vision_result.camera_id,
        vision_result.frame_id,
        vision_result.captured_at,
        np.zeros((16, 16, 3), dtype=np.uint8),
    )
    event_snapshot.attach_event_snapshots(packet, vision_result)
    assert vision_result.events[0].metadata["snapshot_blurred"] is False


def test_event_service_rechecks_persisted_identity_gate_before_db_and_notification():
    import asyncio

    camera_id = camera_service.desired_states()[0]["id"]
    camera_service.set_identity_enabled(camera_id, False)
    vision_result = result()
    vision_result.camera_id = camera_id
    vision_result.events.clear()
    VisionProductPolicy().apply(vision_result)
    unknown = next(event for event in vision_result.events if event.type == "unknown_person")
    request = VisionEventAdapter().adapt(
        VisionResult(
            camera_id,
            vision_result.frame_id,
            vision_result.captured_at,
            vision_result.processed_at,
            vision_result.processing_ms,
            events=[unknown],
        )
    )[0]

    accepted = asyncio.run(EventService().create(request))
    assert accepted.accepted is False
    with database_connection() as connection:
        assert connection.execute(
            "SELECT 1 FROM events WHERE id = ?",
            (stable_uuid(unknown.metadata["event_id"], "event"),),
        ).fetchone() is None
