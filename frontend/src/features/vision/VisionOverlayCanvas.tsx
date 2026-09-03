import { useEffect, useLayoutEffect, useRef, type RefObject } from "react";
import type { CameraVisionDetection, CameraVisionResult } from "../../api/cameras";
import {
  emptyVisionOverlayState,
  updateVisionOverlayState,
  visionActionPresentation,
  visionBBoxLabelLayout,
  type VisionOverlayState,
} from "./visionOverlayState";

type MediaElement = HTMLVideoElement | HTMLImageElement;
const DISPLAY_BBOX_HORIZONTAL_INSET_RATIO = 0.025;
const BBOX_LABEL_PADDING = 4;

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
  const visibleRef = useRef(visible);
  const activeRef = useRef(active);
  const resetKeyRef = useRef(resetKey);
  const drawRef = useRef<() => void>(() => undefined);
  visibleRef.current = visible;
  activeRef.current = active;
  resetKeyRef.current = resetKey;

  useLayoutEffect(() => {
    visualStateRef.current = emptyVisionOverlayState(resetKey);
    ignoredResultRef.current = result;
    const canvas = canvasRef.current;
    canvas?.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
  }, [active, resetKey]);

  const draw = () => {
    const canvas = canvasRef.current;
    const media = mediaRef.current;
    if (!canvas || !media) return;
    const bounds = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const backingWidth = Math.max(1, Math.round(bounds.width * dpr));
    const backingHeight = Math.max(1, Math.round(bounds.height * dpr));
    if (canvas.width !== backingWidth || canvas.height !== backingHeight) {
      canvas.width = backingWidth;
      canvas.height = backingHeight;
    }
    const context = canvas.getContext("2d");
    if (!context) return;
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, bounds.width, bounds.height);
    if (!activeRef.current || bounds.width <= 0 || bounds.height <= 0) return;
    const refreshed = updateVisionOverlayState(
      visualStateRef.current, null, performance.now(), activeRef.current, resetKeyRef.current,
    );
    visualStateRef.current = refreshed.state;
    const [mediaWidth, mediaHeight] = intrinsicSize(media);
    if (mediaWidth <= 0 || mediaHeight <= 0) return;
    const mediaScale = Math.min(bounds.width / mediaWidth, bounds.height / mediaHeight);
    const renderedWidth = mediaWidth * mediaScale;
    const renderedHeight = mediaHeight * mediaScale;
    const offsetX = (bounds.width - renderedWidth) / 2;
    const offsetY = (bounds.height - renderedHeight) / 2;
    const fontSize = Math.max(11, Math.min(15, bounds.width / 70));
    context.font = `600 ${fontSize}px system-ui`;
    context.lineWidth = 2;
    const displayResult = refreshed.display;
    const actionPresentation = visionActionPresentation(
      displayResult,
      refreshed.state,
      refreshed.actionDisplay,
    );
    const actionColor = actionPresentation.tone === "fall" ? "#f87171" : "#86efac";
    context.strokeStyle = actionPresentation.tone === "fall" ? "#ef4444" : "#00ff00";

    const drawLabel = (text: string, x: number, y: number, maxWidth: number, color = "#fff") => {
      const paddingX = 5;
      const labelHeight = fontSize + 9;
      const labelWidth = Math.min(maxWidth, context.measureText(text).width + paddingX * 2);
      const labelX = Math.max(offsetX, Math.min(x, offsetX + renderedWidth - labelWidth));
      const labelY = Math.max(offsetY, Math.min(y, offsetY + renderedHeight - labelHeight));
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

    if (!visibleRef.current || !displayResult) return;
    const sourceWidth = finiteNumber(displayResult.metadata.bbox_source_width) && displayResult.metadata.bbox_source_width > 0
      ? displayResult.metadata.bbox_source_width : mediaWidth;
    const sourceHeight = finiteNumber(displayResult.metadata.bbox_source_height) && displayResult.metadata.bbox_source_height > 0
      ? displayResult.metadata.bbox_source_height : mediaHeight;
    const scaleX = renderedWidth / sourceWidth;
    const scaleY = renderedHeight / sourceHeight;
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
      if (DISPLAY_BBOX_HORIZONTAL_INSET_RATIO >= 0 && DISPLAY_BBOX_HORIZONTAL_INSET_RATIO < 0.2 && width >= 20) {
        const inset = width * DISPLAY_BBOX_HORIZONTAL_INSET_RATIO;
        x += inset;
        width -= inset * 2;
      }
      context.strokeRect(x, y, width, height);
      const labelHeight = fontSize + 9;
      const labelLayout = visionBBoxLabelLayout(
        x,
        y,
        labelHeight,
        offsetY,
        BBOX_LABEL_PADDING,
      );
      drawLabel(identityLabel(detection), labelLayout.identityX, labelLayout.identityY, width);
      if (!actionDrawn && actionPresentation.placement === "bbox" && refreshed.actionDisplay) {
        context.save();
        context.beginPath();
        context.rect(x, y, width, height);
        context.clip();
        drawLabel(
          refreshed.actionDisplay,
          labelLayout.actionX,
          labelLayout.actionY,
          Math.max(1, width - BBOX_LABEL_PADDING * 2),
          actionColor,
        );
        context.restore();
        actionDrawn = true;
      }
    }
  };
  drawRef.current = draw;

  useEffect(() => {
    const canvas = canvasRef.current;
    const media = mediaRef.current;
    if (!canvas || !media) return;
    const redraw = () => drawRef.current();
    const observer = new ResizeObserver(redraw);
    observer.observe(canvas.parentElement ?? canvas);
    media.addEventListener("loadedmetadata", redraw);
    media.addEventListener("load", redraw);
    redraw();
    return () => {
      observer.disconnect();
      media.removeEventListener("loadedmetadata", redraw);
      media.removeEventListener("load", redraw);
    };
  }, [mediaRef]);

  useEffect(() => {
    let expiryTimer: number | undefined;
    const usableResult = result !== ignoredResultRef.current ? result : null;
    if (usableResult) ignoredResultRef.current = null;
    const selection = updateVisionOverlayState(
      visualStateRef.current, usableResult, performance.now(), active, resetKey,
    );
    visualStateRef.current = selection.state;
    drawRef.current();
    const scheduleExpiry = () => {
      if (expiryTimer !== undefined) window.clearTimeout(expiryTimer);
      const state = visualStateRef.current;
      const now = performance.now();
      const expiries = [
        state.retained ? state.expiresAt : 0,
        state.retainedAction ? state.actionExpiresAt : 0,
      ].filter((expiry) => expiry > now);
      if (!expiries.length) return;
      expiryTimer = window.setTimeout(() => {
        const refreshed = updateVisionOverlayState(
          visualStateRef.current, null, performance.now(), activeRef.current, resetKeyRef.current,
        );
        visualStateRef.current = refreshed.state;
        drawRef.current();
        scheduleExpiry();
      }, Math.max(0, Math.min(...expiries) - now) + 1);
    };
    scheduleExpiry();
    return () => {
      if (expiryTimer !== undefined) window.clearTimeout(expiryTimer);
    };
  }, [active, resetKey, result]);

  useEffect(() => {
    drawRef.current();
  }, [visible]);

  useEffect(() => () => {
    visualStateRef.current = emptyVisionOverlayState(resetKeyRef.current);
  }, []);

  return <canvas ref={canvasRef} className="vision-overlay-canvas" aria-hidden="true" />;
}
