import { useEffect, useRef } from "react";
import type { CameraVisionResult } from "../../api/cameras";
import { VisionOverlayCanvas } from "../vision/VisionOverlayCanvas";
import { useWebcam } from "./WebcamProvider";

interface WebcamViewProps {
  cameraId: string;
  className?: string;
  result?: CameraVisionResult | null;
  showBoxes?: boolean;
  visionActive?: boolean;
  overlayResetKey?: string;
}

export function WebcamView({ cameraId, className, result=null, showBoxes = false, visionActive=false, overlayResetKey=cameraId }: WebcamViewProps) {
  const { cameraId: activeCameraId, stream, error } = useWebcam();
  const videoRef = useRef<HTMLVideoElement>(null);
  const availableStream = activeCameraId === cameraId ? stream : null;

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.srcObject = availableStream;
    if (availableStream) void video.play().catch(() => undefined);
    return () => { video.srcObject = null; };
  }, [availableStream]);

  if (!availableStream) {
    return <span className="webcam-permission-state">{error ?? "Đang chờ quyền truy cập webcam…"}</span>;
  }
  return <span className={["webcam-view", className].filter(Boolean).join(" ")}>
    <video ref={videoRef} autoPlay muted playsInline />
    <VisionOverlayCanvas mediaRef={videoRef} result={result} visible={showBoxes} active={visionActive} resetKey={overlayResetKey} />
  </span>;
}
