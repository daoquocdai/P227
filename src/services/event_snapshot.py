import hashlib
import logging
import math

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
        box_width, box_height = x2 - x1, y2 - y1
        pad_x = round(box_width * 0.20)
        pad_top = round(box_height * 0.25)
        pad_bottom = round(box_height * 0.20)
        x1, x2 = max(0, x1 - pad_x), min(width, x2 + pad_x)
        y1, y2 = max(0, y1 - pad_top), min(height, y2 + pad_bottom)
        if x2 <= x1 or y2 <= y1:
            continue
        roi = output[y1:y2, x1:x2]
        sigma = max(3.0, min(x2 - x1, y2 - y1) / 6.0)
        output[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (0, 0), sigma)
        blurred += 1
    return output, blurred


def _source_person_boxes(result):
    geometry = result.metadata.get("geometry", {})
    scale = float(geometry.get("scale", 1.0))
    pad_x = float(geometry.get("pad_x", 0.0))
    pad_y = float(geometry.get("pad_y", 0.0))
    if scale <= 0:
        return []
    boxes = []
    for detection in result.detections:
        if detection.bbox_xyxy is None:
            continue
        x1, y1, x2, y2 = detection.bbox_xyxy
        boxes.append(
            (
                (x1 - pad_x) / scale,
                (y1 - pad_y) / scale,
                (x2 - pad_x) / scale,
                (y2 - pad_y) / scale,
                detection,
            )
        )
    return boxes


def _clip_box(box, width, height):
    x1, y1, x2, y2 = (int(round(value)) for value in box)
    x1, x2 = max(0, x1), min(width, x2)
    y1, y2 = max(0, y1), min(height, y2)
    return None if x2 <= x1 or y2 <= y1 else (x1, y1, x2, y2)


def _map_detected_boxes(boxes, *, origin_x, origin_y, scale, rotation, crop_width, crop_height):
    mapped = []
    for x1, y1, x2, y2 in boxes:
        x1, y1, x2, y2 = (value / scale for value in (x1, y1, x2, y2))
        if rotation == 90:  # cv2.ROTATE_90_CLOCKWISE
            x1, y1, x2, y2 = y1, crop_height - x2, y2, crop_height - x1
        elif rotation == -90:  # cv2.ROTATE_90_COUNTERCLOCKWISE
            x1, y1, x2, y2 = crop_width - y2, x1, crop_width - y1, x2
        mapped.append((x1 + origin_x, y1 + origin_y, x2 + origin_x, y2 + origin_y))
    return mapped


def _detect_in_person_crops(frame, result, detector):
    height, width = frame.shape[:2]
    for rotation in (0, 90, -90):
        for px1, py1, px2, py2, _detection in _source_person_boxes(result):
            clipped = _clip_box((px1, py1, px2, py2), width, height)
            if clipped is None:
                continue
            x1, y1, x2, y2 = clipped
            crop = frame[y1:y2, x1:x2]
            crop_height, crop_width = crop.shape[:2]
            scale = 2.0 if max(crop_width, crop_height) < 640 else 1.0
            candidate = crop
            if scale != 1.0:
                candidate = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            if rotation == 90:
                candidate = cv2.rotate(candidate, cv2.ROTATE_90_CLOCKWISE)
            elif rotation == -90:
                candidate = cv2.rotate(candidate, cv2.ROTATE_90_COUNTERCLOCKWISE)
            boxes = detector(candidate)
            if boxes:
                method = "person_crop_detector" if rotation == 0 else f"rotated_crop_{rotation}"
                return (
                    _map_detected_boxes(
                        boxes,
                        origin_x=x1,
                        origin_y=y1,
                        scale=scale,
                        rotation=rotation,
                        crop_width=crop_width,
                        crop_height=crop_height,
                    ),
                    method,
                )
    return [], None


def _pose_head_boxes(frame, result):
    height, width = frame.shape[:2]
    geometry = result.metadata.get("geometry", {})
    vision_width = float(geometry.get("vision_width", width))
    vision_height = float(geometry.get("vision_height", height))
    scale = float(geometry.get("scale", 1.0))
    pad_x = float(geometry.get("pad_x", 0.0))
    pad_y = float(geometry.get("pad_y", 0.0))
    if scale <= 0:
        return []

    def source_point(point):
        return ((point[0] * vision_width - pad_x) / scale, (point[1] * vision_height - pad_y) / scale)

    boxes = []
    if result.metadata.get("privacy_pose_frame_id") != result.frame_id:
        return boxes
    points = result.metadata.get("privacy_head_shoulders") or {}
    for _x1, _y1, _x2, _y2, _detection in _source_person_boxes(result):
        try:
            head = tuple(float(value) for value in points["head"])
            left = tuple(float(value) for value in points["left_shoulder"])
            right = tuple(float(value) for value in points["right_shoulder"])
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(value) and 0.0 <= value <= 1.0 for point in (head, left, right) for value in point):
            continue
        head = source_point(head)
        left = source_point(left)
        right = source_point(right)
        shoulder_distance = math.dist(left, right)
        if shoulder_distance < 8:
            continue
        head_x, head_y = head
        radius = max(12.0, shoulder_distance * 0.65)
        clipped = _clip_box((head_x - radius, head_y - radius, head_x + radius, head_y + radius), width, height)
        if clipped is not None:
            boxes.append(clipped)
    return boxes


def _privacy_boxes(frame, result, exact_boxes, detector):
    if exact_boxes:
        return exact_boxes, "exact_face_bbox"
    if detector is not None:
        boxes = detector(frame)
        if boxes:
            return boxes, "full_frame_detector"
        boxes, method = _detect_in_person_crops(frame, result, detector)
        if boxes:
            return boxes, method
    boxes = _pose_head_boxes(frame, result)
    return (boxes, "pose_head_roi") if boxes else ([], "no_safe_snapshot")


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


def attach_event_snapshots(packet, result, privacy_face_detector=None) -> None:
    """Save evidence from the exact FramePacket paired with the event result."""
    if not result.events:
        return
    exact_face_boxes = _exact_source_face_boxes(result)
    privacy_result = None
    for index, event in enumerate(result.events):
        if valid_snapshot_name(event.metadata.get("snapshot_path")):
            continue
        try:
            if event.type in {"fall_confirmed", "unknown_person"}:
                if privacy_result is None:
                    privacy_result = _privacy_boxes(
                        packet.frame, result, exact_face_boxes, privacy_face_detector
                    )
                face_boxes, privacy_method = privacy_result
                event.metadata["snapshot_privacy_method"] = privacy_method
            else:
                face_boxes = exact_face_boxes
            frame, blurred_faces = blur_faces(packet.frame, face_boxes)
            # Never persist an unblurred Unknown-person image. A locked identity
            # may carry a face bbox cached from an earlier frame; in that case
            # keep delivering the event, but omit unsafe visual evidence.
            if event.type == "unknown_person" and blurred_faces == 0:
                continue
            if event.type == "fall_confirmed" and blurred_faces == 0:
                continue
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
