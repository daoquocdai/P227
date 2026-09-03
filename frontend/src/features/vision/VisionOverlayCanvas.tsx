import { useEffect, useLayoutEffect, useRef, type RefObject } from "react";
import type { CameraVisionDetection, CameraVisionResult } from "../../api/cameras";
import { emptyVisionOverlayState, formatActionDisplay, updateVisionOverlayState, type VisionOverlayState } from "./visionOverlayState";

type MediaElement = HTMLVideoElement | HTMLImageElement;
const DISPLAY_BBOX_HORIZONTAL_INSET_RATIO = 0.025;

interface VisionOverlayCanvasProps {
  result: CameraVisionResult | null;
  visible: boolean;
  active: boolean;
  resetKey: string;
  mediaRef: RefObject<MediaElement | null>;
}

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function identityLabel(detection: CameraVisionDetection): string {
  const metadata = detection.metadata;
  const state = typeof metadata.identity_state === "string" ? metadata.identity_state : null;
  const name = typeof metadata.identity_name === "string" && metadata.identity_name.trim()
    ? metadata.identity_name.trim() : null;
  if (state === "LOCKED_KNOWN" && name) return name;
  if (state === "LOCKED_UNKNOWN") return "Người lạ";
  if (state && state !== "DISABLED") return "Không xác định";
  return detection.label;
}

function intrinsicSize(media: MediaElement): [number, number] {
  return media instanceof HTMLVideoElement
    ? [media.videoWidth, media.videoHeight]
    : [media.naturalWidth, media.naturalHeight];
}

export function VisionOverlayCanvas({ result, visible, active, resetKey, mediaRef }: VisionOverlayCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const visualStateRef = useRef<VisionOverlayState>(emptyVisionOverlayState(resetKey));
  const ignoredResultRef = useRef<CameraVisionResult | null>(null);

  useLayoutEffect(() => {
    visualStateRef.current = emptyVisionOverlayState(resetKey);
    ignoredResultRef.current = result;
    const canvas = canvasRef.current;
    canvas?.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
  }, [active, resetKey]);

  useEffect(() => () => {
    visualStateRef.current = emptyVisionOverlayState(resetKey);
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    const media = mediaRef.current;
    if (!canvas || !media) return;

    let expiryTimer: number | undefined;
    const usableResult = result !== ignoredResultRef.current ? result : null;
    const selection = updateVisionOverlayState(
      visualStateRef.current, usableResult, performance.now(), active, resetKey,
    );
    visualStateRef.current = selection.state;

    const draw = () => {
      const bounds = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.round(bounds.width * dpr));
      canvas.height = Math.max(1, Math.round(bounds.height * dpr));
      const context = canvas.getContext("2d");
      if (!context) return;
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      context.clearRect(0, 0, bounds.width, bounds.height);
      if (!visible || !active || bounds.width <= 0 || bounds.height <= 0) return;
      const refreshed = updateVisionOverlayState(
        visualStateRef.current, null, performance.now(), active, resetKey,
      );
      visualStateRef.current = refreshed.state;
      const displayResult = refreshed.display;
      if (!displayResult) {
        return;
      }

      const [mediaWidth, mediaHeight] = intrinsicSize(media);
      if (mediaWidth <= 0 || mediaHeight <= 0) return;
      const sourceWidth = finiteNumber(displayResult.metadata.bbox_source_width) && displayResult.metadata.bbox_source_width > 0
        ? displayResult.metadata.bbox_source_width : mediaWidth;
      const sourceHeight = finiteNumber(displayResult.metadata.bbox_source_height) && displayResult.metadata.bbox_source_height > 0
        ? displayResult.metadata.bbox_source_height : mediaHeight;
      const mediaScale = Math.min(bounds.width / mediaWidth, bounds.height / mediaHeight);
      const renderedWidth = mediaWidth * mediaScale;
      const renderedHeight = mediaHeight * mediaScale;
      const offsetX = (bounds.width - renderedWidth) / 2;
      const offsetY = (bounds.height - renderedHeight) / 2;
      const scaleX = renderedWidth / sourceWidth;
      const scaleY = renderedHeight / sourceHeight;
      const fontSize = Math.max(11, Math.min(15, bounds.width / 70));
      context.font = `600 ${fontSize}px system-ui`;
      context.lineWidth = 2;
      context.strokeStyle = "#00ff00";

      let actionDrawn = false;
      for (const detection of displayResult.detections) {
        const bbox = detection.bbox_xyxy;
        if (!bbox || bbox.length !== 4 || !bbox.every(finiteNumber)) continue;
        const x1 = Math.max(0, Math.min(sourceWidth, bbox[0]));
        const y1 = Math.max(0, Math.min(sourceHeight, bbox[1]));
        const x2 = Math.max(0, Math.min(sourceWidth, bbox[2]));
        const y2 = Math.max(0, Math.min(sourceHeight, bbox[3]));
        if (x2 <= x1 || y2 <= y1) continue;
        let x = offsetX + x1 * scaleX;
        const y = offsetY + y1 * scaleY;
        let width = (x2 - x1) * scaleX;
        const height = (y2 - y1) * scaleY;
        // Presentation-only inset; backend bbox remains authoritative for
        // tracking, Identity, event, and snapshot semantics.
        if (DISPLAY_BBOX_HORIZONTAL_INSET_RATIO >= 0 && DISPLAY_BBOX_HORIZONTAL_INSET_RATIO < 0.2 && width >= 20) {
          const inset = width * DISPLAY_BBOX_HORIZONTAL_INSET_RATIO;
          x += inset;
          width -= inset * 2;
        }
        context.strokeRect(x, y, width, height);

        const drawLabel = (text: string, desiredY: number, insideY: number, color = "#fff") => {
          const paddingX = 5;
          const labelHeight = fontSize + 9;
          const labelWidth = Math.min(width, context.measureText(text).width + paddingX * 2);
          const labelX = Math.max(offsetX, Math.min(x, offsetX + renderedWidth - labelWidth));
          const labelY = desiredY >= offsetY ? desiredY : insideY;
          context.fillStyle = "rgba(15, 23, 42, 0.82)";
          context.fillRect(labelX, labelY, labelWidth, labelHeight);
          context.fillStyle = color;
          context.save();
          context.beginPath();
          context.rect(labelX, labelY, labelWidth, labelHeight);
          context.clip();
          context.fillText(text, labelX + paddingX, labelY + fontSize + 3);
          context.restore();
        };

        const labelHeight = fontSize + 9;
        drawLabel(identityLabel(detection), y, y);
        const action = formatActionDisplay(displayResult.metadata);
        if (!actionDrawn && action) {
          const fallState = typeof displayResult.metadata.fall_state === "string" ? displayResult.metadata.fall_state : "CLEAR";
          const actionY = Math.min(y + labelHeight, Math.max(y, y + height - labelHeight));
          drawLabel(action, actionY, actionY,
            fallState === "CLEAR" ? "#86efac" : "#f87171");
          actionDrawn = true;
        }
      }
    };

    const observer = new ResizeObserver(draw);
    observer.observe(canvas.parentElement ?? canvas);
    media.addEventListener("loadedmetadata", draw);
    media.addEventListener("load", draw);
    draw();
    if (selection.state.retained && selection.display !== usableResult) {
      expiryTimer = window.setTimeout(draw, Math.max(0, selection.state.expiresAt - performance.now()));
    }
    return () => {
      if (expiryTimer !== undefined) window.clearTimeout(expiryTimer);
      observer.disconnect();
      media.removeEventListener("loadedmetadata", draw);
      media.removeEventListener("load", draw);
    };
  }, [active, mediaRef, resetKey, result, visible]);

  return <canvas ref={canvasRef} className="vision-overlay-canvas" aria-hidden="true" />;
}
