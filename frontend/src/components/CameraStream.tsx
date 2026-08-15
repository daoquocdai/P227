interface CameraStreamProps {
  cameraId: string;
  streamReady?: boolean;
  streamUrl?: string | null;
  playbackUrl?: string | null; // Compatibility only; production viewing uses MJPEG.
  className?: string;
  onError?: () => void;
  showBoxes?: boolean;
  showIdentity?: boolean;
}

export function CameraStream({ cameraId, streamReady, streamUrl, className, onError, showBoxes=true, showIdentity=true }: CameraStreamProps) {
  if (streamReady && streamUrl) {
    const separator=streamUrl.includes("?")?"&":"?";
    const configured=`${streamUrl}${separator}boxes=${showBoxes}&identity=${showIdentity}`;
    const streamClassName=["camera-stream-image",className].filter(Boolean).join(" ");
    return <img className={streamClassName} src={configured} alt={`Luồng trực tiếp ${cameraId}`} onError={onError} />;
  }
  return null;
}
