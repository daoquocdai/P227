interface CameraStreamProps {
  cameraId: string;
  streamReady?: boolean;
  streamUrl?: string | null;
  playbackUrl?: string | null;
  className?: string;
  onError?: () => void;
}

export function CameraStream({ cameraId, streamReady, streamUrl, playbackUrl, className, onError }: CameraStreamProps) {
  if (streamReady && streamUrl) {
    return <img className={className} src={streamUrl} alt={`Luồng trực tiếp ${cameraId}`} onError={onError} />;
  }
  if (!playbackUrl) return null;
  const rememberFrame = (video: HTMLVideoElement) => {
    if (Number.isFinite(video.currentTime)) localStorage.setItem(`camera-preview-time:${cameraId}`, String(video.currentTime));
  };
  return <video className={className} src={playbackUrl} autoPlay loop muted playsInline preload="auto" onTimeUpdate={(event) => rememberFrame(event.currentTarget)} onError={onError} />;
}
