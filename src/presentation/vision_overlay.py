import cv2


def render_vision(frame, result, *, show_boxes=True, show_identity=True, show_fall=True):
    """Render backend Vision DTOs whose boxes are already source pixels."""
    output = frame.copy()
    if result is None:
        return output
    for detection in result.detections:
        if detection.bbox_xyxy is None:
            continue
        x1, y1, x2, y2 = (int(value) for value in detection.bbox_xyxy)
        identity = detection.metadata
        if show_boxes:
            cv2.rectangle(output, (x1, y1), (x2, y2), (0, 255, 0), 2)
        if show_identity and identity.get("identity_status") == "KNOWN" and identity.get("identity_name"):
            cv2.putText(
                output,
                str(identity["identity_name"]),
                (x1, min(output.shape[0] - 8, y2 + 22)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
            )
        elif show_identity and identity.get("identity_state") == "LOCKED_UNKNOWN":
            cv2.putText(
                output,
                "Unknown",
                (x1, min(output.shape[0] - 8, y2 + 22)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
            )
    if show_fall:
        action = result.metadata.get("current_action", "Waiting for frames...")
        color = (0, 0, 255) if result.metadata.get("fall_state") not in {None, "CLEAR"} else (0, 255, 0)
        cv2.putText(output, f"Action: {action}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)
    return output
