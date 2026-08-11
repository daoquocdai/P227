interface CameraStreamProps {
  cameraId: string;
  streamReady?: boolean;
  streamUrl?: string | null;
  playbackUrl?: string | null; // Compatibility only; production viewing uses MJPEG.
  className?: string;
  onError?: () => void;
}

export function CameraStream({ cameraId, streamReady, streamUrl, className, onError }: CameraStreamProps) {
  if (streamReady && streamUrl) {
    return <img className={className} src={streamUrl} alt={`Luồng trực tiếp ${cameraId}`} onError={onError} />;
  }
  return null;
}
