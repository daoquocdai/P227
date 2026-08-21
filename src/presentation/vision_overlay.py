from __future__ import annotations

from dataclasses import dataclass

import cv2


@dataclass(frozen=True, slots=True)
class TextOverlay:
    text: str
    origin: tuple[int, int]
    background: tuple[int, int, int, int]
    font_scale: float
    thickness: int
    color: tuple[int, int, int]


def _text_overlay(
    text: str,
    *,
    desired_x: int,
    desired_y: int,
    frame_width: int,
    safe_top: int,
    safe_bottom: int,
    font_scale: float,
    thickness: int,
    color: tuple[int, int, int],
) -> TextOverlay:
    text_size, baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
    text_width, text_height = text_size
    padding = max(4, min(10, round(min(frame_width, safe_bottom) * 0.006)))
    x = max(padding, min(desired_x, frame_width - text_width - padding * 2))
    y = max(safe_top + text_height + padding, min(desired_y, safe_bottom - baseline - padding))
    background = (
        x - padding,
        y - text_height - padding,
        min(frame_width - 1, x + text_width + padding),
        min(safe_bottom, y + baseline + padding),
    )
    return TextOverlay(text, (x, y), background, font_scale, thickness, color)


def calculate_text_overlays(frame_shape, result, *, show_identity=True, show_fall=True) -> list[TextOverlay]:
    """Lay out compact Vision labels away from CameraPage's edge controls."""
    frame_height, frame_width = frame_shape[:2]
    shorter_edge = min(frame_width, frame_height)
    font_scale = max(0.55, min(1.0, shorter_edge / 1080 * 0.78))
    thickness = 1 if shorter_edge < 720 else 2
    edge_margin = max(8, round(frame_height * 0.08))
    safe_top = min(frame_height - 2, edge_margin)
    safe_bottom = max(safe_top + 1, frame_height - edge_margin)
    line_gap = max(6, round(shorter_edge * 0.008))
    overlays: list[TextOverlay] = []

    primary_detection = next((item for item in result.detections if item.bbox_xyxy is not None), None)
    if primary_detection is not None:
        x1, y1, _x2, _y2 = (int(value) for value in primary_detection.bbox_xyxy)
        desired_x = max(0, x1) + line_gap
        desired_y = max(0, y1) + line_gap
        identity = primary_detection.metadata
        identity_text = None
        if show_identity and identity.get("identity_status") == "KNOWN" and identity.get("identity_name"):
            identity_text = str(identity["identity_name"])
        elif show_identity and identity.get("identity_state") == "LOCKED_UNKNOWN":
            identity_text = "Unknown"
        if identity_text:
            label = _text_overlay(
                identity_text,
                desired_x=desired_x,
                desired_y=desired_y,
                frame_width=frame_width,
                safe_top=safe_top,
                safe_bottom=safe_bottom,
                font_scale=font_scale,
                thickness=thickness,
                color=(255, 255, 255),
            )
            overlays.append(label)
            desired_y = label.background[3] + line_gap + max(24, round(shorter_edge * 0.035))
    else:
        desired_x = max(8, round(frame_width * 0.04))
        desired_y = safe_top + max(8, round(frame_height * 0.04))

    if show_fall:
        action = result.metadata.get("current_action", "Waiting for frames...")
        color = (0, 0, 255) if result.metadata.get("fall_state") not in {None, "CLEAR"} else (0, 255, 0)
        overlays.append(
            _text_overlay(
                f"Action: {action}",
                desired_x=desired_x,
                desired_y=desired_y,
                frame_width=frame_width,
                safe_top=safe_top,
                safe_bottom=safe_bottom,
                font_scale=font_scale,
                thickness=thickness,
                color=color,
            )
        )
    return overlays


def render_vision(frame, result, *, show_boxes=True, show_identity=True, show_fall=True):
    """Render backend Vision DTOs whose boxes are already source pixels."""
    output = frame.copy()
    if result is None:
        return output
    if show_boxes:
        for detection in result.detections:
            if detection.bbox_xyxy is None:
                continue
            x1, y1, x2, y2 = (int(value) for value in detection.bbox_xyxy)
            cv2.rectangle(output, (x1, y1), (x2, y2), (0, 255, 0), 2)
    for overlay in calculate_text_overlays(
        output.shape,
        result,
        show_identity=show_identity,
        show_fall=show_fall,
    ):
        cv2.rectangle(output, overlay.background[:2], overlay.background[2:], (24, 24, 24), cv2.FILLED)
        cv2.putText(
            output,
            overlay.text,
            overlay.origin,
            cv2.FONT_HERSHEY_SIMPLEX,
            overlay.font_scale,
            overlay.color,
            overlay.thickness,
            cv2.LINE_AA,
        )
    return output
