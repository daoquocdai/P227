import cv2


def render_vision(frame, result, *, show_boxes=True, show_identity=True, show_fall=True):
    """Presentation-only renderer; it never invokes inference."""
    output = frame.copy()
    if result is None:
        return output
    metadata = result.metadata
    geometry = metadata.get("geometry", {})
    scale = float(geometry.get("scale", 1.0))
    pad_x = float(geometry.get("pad_x", 0.0))
    pad_y = float(geometry.get("pad_y", 0.0))
    for detection in result.detections:
        if detection.bbox_xyxy is None:
            continue
        x1, y1, x2, y2 = detection.bbox_xyxy
        source_box = [int((x1-pad_x)/scale), int((y1-pad_y)/scale), int((x2-pad_x)/scale), int((y2-pad_y)/scale)]
        sx1,sy1,sx2,sy2=source_box
        identity=detection.metadata
        if show_boxes:
            cv2.rectangle(output,(sx1,sy1),(sx2,sy2),(0,255,0),2)
            cv2.putText(output,f"ID:{detection.track_id if detection.track_id is not None else '?'}",(sx1,max(18,sy1-10)),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,255,0),2)
        identity_status = identity.get("identity_status")
        identity_state = identity.get("identity_state")
        if show_identity and identity_status == "KNOWN" and identity.get("identity_name"):
            cv2.putText(output,identity["identity_name"],(sx1,min(output.shape[0]-8,sy2+22)),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255),2)
        elif show_identity and identity_status == "UNKNOWN" and identity_state == "LOCKED_UNKNOWN":
            cv2.putText(output,"Unknown",(sx1,min(output.shape[0]-8,sy2+22)),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255),2)
    if show_fall:
        action=metadata.get("current_action","Waiting for frames...")
        color=(0,0,255) if action=="Nga!" else (0,255,0)
        cv2.putText(output,f"Action: {action}",(20,40),cv2.FONT_HERSHEY_SIMPLEX,1,color,2)
    return output
