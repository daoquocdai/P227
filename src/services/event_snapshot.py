import hashlib
import logging

import cv2

from src.services.media_paths import SNAPSHOT_ROOT, valid_snapshot_name

logger = logging.getLogger(__name__)


def blur_faces(frame, face_boxes):
    """Copy a frame and blur only valid, clipped face ROIs."""
    output = frame.copy()
    height, width = output.shape[:2]
    blurred = 0
    for box in face_boxes:
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            x1, y1, x2, y2 = (int(value) for value in box)
        except (TypeError, ValueError):
            continue
        x1, x2 = max(0, x1), min(width, x2)
        y1, y2 = max(0, y1), min(height, y2)
        if x2 <= x1 or y2 <= y1:
            continue
        roi = output[y1:y2, x1:x2]
        sigma = max(3.0, min(x2 - x1, y2 - y1) / 6.0)
        output[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (0, 0), sigma)
        blurred += 1
    return output, blurred


def _exact_source_face_boxes(result):
    geometry = result.metadata.get("geometry", {})
    scale = float(geometry.get("scale", 1.0))
    pad_x = float(geometry.get("pad_x", 0.0))
    pad_y = float(geometry.get("pad_y", 0.0))
    if scale <= 0:
        return []
    boxes = []
    for detection in result.detections:
        metadata = detection.metadata
        if metadata.get("identity_face_bbox_frame_id") != result.frame_id:
            continue
        face_box = metadata.get("identity_face_bbox_xyxy")
        if not isinstance(face_box, (list, tuple)) or len(face_box) != 4:
            continue
        # InsightFace coordinates are relative to the padded person crop.
        if detection.bbox_xyxy is None:
            continue
        person_x1, person_y1, _, _ = detection.bbox_xyxy
        vx1, vy1, vx2, vy2 = face_box
        boxes.append(
            (
                (person_x1 + vx1 - pad_x) / scale,
                (person_y1 + vy1 - pad_y) / scale,
                (person_x1 + vx2 - pad_x) / scale,
                (person_y1 + vy2 - pad_y) / scale,
            )
        )
    return boxes


def attach_event_snapshots(packet, result) -> None:
    """Save evidence from the exact FramePacket paired with the event result."""
    if not result.events:
        return
    for index, event in enumerate(result.events):
        if valid_snapshot_name(event.metadata.get("snapshot_path")):
            continue
        try:
            frame, blurred_faces = blur_faces(packet.frame, _exact_source_face_boxes(result))
            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not ok:
                raise RuntimeError("OpenCV could not encode the event snapshot")
            identity = f"{packet.camera_id}:{packet.frame_id}:{packet.captured_at}:{index}:{event.type}".encode()
            digest = hashlib.sha256(identity).hexdigest()[:16]
            safe_camera = "".join(char if char.isalnum() or char in "-_" else "-" for char in packet.camera_id)
            filename = f"vision-{safe_camera}-{packet.frame_id}-{digest}.jpg"
            SNAPSHOT_ROOT.mkdir(parents=True, exist_ok=True)
            destination = SNAPSHOT_ROOT / filename
            temporary = destination.with_suffix(".jpg.tmp")
            temporary.write_bytes(encoded.tobytes())
            temporary.replace(destination)
            event.metadata["snapshot_path"] = filename
            event.metadata["snapshot_blurred"] = blurred_faces > 0
            event.metadata["snapshot_blurred_faces"] = blurred_faces
        except Exception:  # noqa: BLE001 - evidence failure must not stop event delivery
            logger.exception(
                "Could not persist Vision event snapshot camera=%s frame=%s",
                packet.camera_id,
                packet.frame_id,
            )
