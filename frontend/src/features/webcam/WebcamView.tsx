import { useEffect, useRef } from "react";
import type { CameraVisionResult } from "../../api/cameras";
import { useWebcam } from "./WebcamProvider";

interface WebcamViewProps {
  cameraId: string;
  className?: string;
  result?: CameraVisionResult | null;
  showBoxes?: boolean;
  showIdentity?: boolean;
}

export function WebcamView({ cameraId, className, result, showBoxes = false, showIdentity = false }: WebcamViewProps) {
  const { cameraId: activeCameraId, stream, error } = useWebcam();
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const availableStream = activeCameraId === cameraId ? stream : null;

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.srcObject = availableStream;
    if (availableStream) void video.play().catch(() => undefined);
    return () => { video.srcObject = null; };
  }, [availableStream]);

  useEffect(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;
    const draw = () => {
      const bounds = canvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.round(bounds.width * ratio));
      canvas.height = Math.max(1, Math.round(bounds.height * ratio));
      const context = canvas.getContext("2d");
      if (!context) return;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, bounds.width, bounds.height);
      if (!showBoxes || !result || !video.videoWidth || !video.videoHeight) return;
      const scale = Math.min(bounds.width / video.videoWidth, bounds.height / video.videoHeight);
      const offsetX = (bounds.width - video.videoWidth * scale) / 2;
      const offsetY = (bounds.height - video.videoHeight * scale) / 2;
      context.font = "600 13px system-ui";
      context.lineWidth = 2;
      for (const detection of result.detections) {
        const bbox = detection.bbox_xyxy;
        if (!bbox) continue;
        const [x1, y1, x2, y2] = bbox;
        const x = offsetX + x1 * scale;
        const y = offsetY + y1 * scale;
        const width = (x2 - x1) * scale;
        const height = (y2 - y1) * scale;
        context.strokeStyle = "#38bdf8";
        context.strokeRect(x, y, width, height);
        const identity = showIdentity && typeof detection.metadata.identity_name === "string"
          ? detection.metadata.identity_name : null;
        const label = identity ?? detection.label;
        const labelWidth = context.measureText(label).width + 10;
        context.fillStyle = "rgba(15, 23, 42, .82)";
        context.fillRect(x, Math.max(0, y - 22), labelWidth, 22);
        context.fillStyle = "#fff";
        context.fillText(label, x + 5, Math.max(15, y - 6));
      }
    };
    const observer = new ResizeObserver(draw);
    observer.observe(canvas);
    video.addEventListener("loadedmetadata", draw);
    draw();
    return () => { observer.disconnect(); video.removeEventListener("loadedmetadata", draw); };
  }, [result, showBoxes, showIdentity]);

  if (!availableStream) {
    return <span className="webcam-permission-state">{error ?? "Đang chờ quyền truy cập webcam…"}</span>;
  }
  return <span className={["webcam-view", className].filter(Boolean).join(" ")}>
    <video ref={videoRef} autoPlay muted playsInline />
    <canvas ref={canvasRef} aria-hidden="true" />
  </span>;
}
