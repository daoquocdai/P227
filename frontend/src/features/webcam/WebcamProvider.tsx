import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { getCameras } from "../../api/cameras";
import { API_BASE_URL, getAuthToken } from "../../api/client";

const WEBCAM_VISION_UPLOAD_FPS = 12;
const MAX_UPLOAD_WIDTH = 960;
const JPEG_QUALITY = 0.72;
const MAX_BUFFERED_BYTES = 512 * 1024;

type WebcamStatus = "idle" | "requesting" | "connecting" | "publishing" | "reconnecting" | "error";

interface WebcamContextValue {
  cameraId: string | null;
  stream: MediaStream | null;
  status: WebcamStatus;
  error: string | null;
}

const WebcamContext = createContext<WebcamContextValue>({ cameraId: null, stream: null, status: "idle", error: null });

export function useWebcam(): WebcamContextValue {
  return useContext(WebcamContext);
}

function websocketUrl(cameraId: string): string {
  const url = new URL(API_BASE_URL, window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `${url.pathname.replace(/\/$/, "")}/cameras/${encodeURIComponent(cameraId)}/webcam`;
  url.search = "";
  url.hash = "";
  return url.toString();
}

export function WebcamProvider({ children }: { children: ReactNode }) {
  const [value, setValue] = useState<WebcamContextValue>({ cameraId: null, stream: null, status: "idle", error: null });
  const sourceVideoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    let disposed = false;
    let generation = 0;
    let activeCameraId: string | null = null;
    let mediaStream: MediaStream | null = null;
    let socket: WebSocket | null = null;
    let uploadTimer: number | null = null;
    let reconnectTimer: number | null = null;
    let reconnectAttempt = 0;
    let encodeInFlight = false;
    let refreshInFlight = false;
    let permissionBlockedCameraId: string | null = null;
    const canvas = document.createElement("canvas");

    const stopPublisher = () => {
      if (uploadTimer !== null) window.clearInterval(uploadTimer);
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      uploadTimer = null;
      reconnectTimer = null;
      const current = socket;
      socket = null;
      current?.close(1000, "publisher stopped");
    };

    const stopCapture = () => {
      generation += 1;
      stopPublisher();
      mediaStream?.getTracks().forEach((track) => track.stop());
      mediaStream = null;
      activeCameraId = null;
      if (sourceVideoRef.current) sourceVideoRef.current.srcObject = null;
      if (!disposed) setValue({ cameraId: null, stream: null, status: "idle", error: null });
    };

    const startUploader = (publisherSocket: WebSocket, stream: MediaStream, expectedGeneration: number) => {
      if (uploadTimer !== null) window.clearInterval(uploadTimer);
      uploadTimer = window.setInterval(() => {
        const video = sourceVideoRef.current;
        if (
          disposed || expectedGeneration !== generation || publisherSocket !== socket ||
          publisherSocket.readyState !== WebSocket.OPEN || encodeInFlight ||
          publisherSocket.bufferedAmount > MAX_BUFFERED_BYTES || !video || video.readyState < 2 ||
          video.videoWidth <= 0 || video.videoHeight <= 0
        ) return;
        const scale = Math.min(1, MAX_UPLOAD_WIDTH / video.videoWidth);
        canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
        canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
        canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
        encodeInFlight = true;
        canvas.toBlob((blob) => {
          if (!blob) { encodeInFlight = false; return; }
          void blob.arrayBuffer().then((payload) => {
            if (
              expectedGeneration === generation && publisherSocket === socket &&
              publisherSocket.readyState === WebSocket.OPEN && publisherSocket.bufferedAmount <= MAX_BUFFERED_BYTES
            ) publisherSocket.send(payload);
          }).finally(() => { encodeInFlight = false; });
        }, "image/jpeg", JPEG_QUALITY);
      }, 1000 / WEBCAM_VISION_UPLOAD_FPS);
      void stream;
    };

    const connectPublisher = (cameraId: string, stream: MediaStream, expectedGeneration: number) => {
      if (disposed || expectedGeneration !== generation || stream !== mediaStream) return;
      stopPublisher();
      setValue({ cameraId, stream, status: reconnectAttempt ? "reconnecting" : "connecting", error: null });
      const publisherSocket = new WebSocket(websocketUrl(cameraId));
      socket = publisherSocket;
      publisherSocket.binaryType = "arraybuffer";
      publisherSocket.onopen = () => {
        const token = getAuthToken();
        if (!token) { publisherSocket.close(4401, "missing auth"); return; }
        publisherSocket.send(JSON.stringify({ type: "auth", token }));
      };
      publisherSocket.onmessage = (event) => {
        if (typeof event.data !== "string") return;
        try {
          const message = JSON.parse(event.data) as { type?: string };
          if (message.type !== "ready") return;
          reconnectAttempt = 0;
          setValue({ cameraId, stream, status: "publishing", error: null });
          startUploader(publisherSocket, stream, expectedGeneration);
        } catch { /* Ignore non-protocol text. */ }
      };
      publisherSocket.onclose = () => {
        if (publisherSocket !== socket || disposed || expectedGeneration !== generation || stream !== mediaStream) return;
        socket = null;
        if (uploadTimer !== null) window.clearInterval(uploadTimer);
        uploadTimer = null;
        const delays = [500, 1000, 2000, 4000, 5000];
        const delay = delays[Math.min(reconnectAttempt, delays.length - 1)];
        reconnectAttempt += 1;
        setValue({ cameraId, stream, status: "reconnecting", error: "Mất kết nối tới Local Hub; đang thử lại." });
        reconnectTimer = window.setTimeout(() => connectPublisher(cameraId, stream, expectedGeneration), delay);
      };
    };

    const ensureCapture = async (cameraId: string) => {
      if (cameraId === activeCameraId && mediaStream) return;
      stopCapture();
      activeCameraId = cameraId;
      const expectedGeneration = generation;
      setValue({ cameraId, stream: null, status: "requesting", error: null });
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } },
          audio: false,
        });
        if (disposed || expectedGeneration !== generation || activeCameraId !== cameraId) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        mediaStream = stream;
        for (const track of stream.getVideoTracks()) {
          track.addEventListener("ended", () => {
            if (stream !== mediaStream) return;
            permissionBlockedCameraId = cameraId;
            stopCapture();
            setValue({ cameraId, stream: null, status: "error", error: "Camera đã ngừng hoặc thiết bị không còn khả dụng." });
          }, { once: true });
        }
        setValue({ cameraId, stream, status: "connecting", error: null });
        if (sourceVideoRef.current) {
          sourceVideoRef.current.srcObject = stream;
          void sourceVideoRef.current.play().catch(() => undefined);
        }
        connectPublisher(cameraId, stream, expectedGeneration);
      } catch {
        permissionBlockedCameraId = cameraId;
        setValue({ cameraId, stream: null, status: "error", error: "Không có quyền truy cập webcam trong trình duyệt." });
      }
    };

    const refresh = async () => {
      if (disposed || refreshInFlight) return;
      refreshInFlight = true;
      try {
        const webcams = (await getCameras()).filter((camera) => camera.active && camera.source_kind === "webcam");
        const target = webcams[0]?.id ?? null;
        if (!target) {
          permissionBlockedCameraId = null;
          if (mediaStream || activeCameraId) stopCapture();
          return;
        }
        if (webcams.length > 1) console.warn("Only one active browser webcam publisher is supported; using", target);
        if (target !== permissionBlockedCameraId) await ensureCapture(target);
      } catch {
        if (mediaStream && activeCameraId) {
          setValue({ cameraId: activeCameraId, stream: mediaStream, status: "reconnecting", error: "Không tải được trạng thái camera." });
        }
      } finally {
        refreshInFlight = false;
      }
    };

    const onCamerasChanged = () => { void refresh(); };
    void refresh();
    const refreshTimer = window.setInterval(() => { void refresh(); }, 5000);
    window.addEventListener("antam:cameras-changed", onCamerasChanged);
    return () => {
      disposed = true;
      window.clearInterval(refreshTimer);
      window.removeEventListener("antam:cameras-changed", onCamerasChanged);
      stopCapture();
    };
  }, []);

  useEffect(() => {
    if (!sourceVideoRef.current) return;
    sourceVideoRef.current.srcObject = value.stream;
    if (value.stream) void sourceVideoRef.current.play().catch(() => undefined);
  }, [value.stream]);

  return <WebcamContext.Provider value={value}>
    {children}
    <video ref={sourceVideoRef} autoPlay muted playsInline aria-hidden="true" style={{ position: "fixed", width: 1, height: 1, opacity: 0, pointerEvents: "none" }} />
  </WebcamContext.Provider>;
}
