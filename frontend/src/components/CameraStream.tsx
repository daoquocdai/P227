import { useEffect, useRef, useState } from "react";
import type { CameraVisionResult } from "../api/cameras";
import { VisionOverlayCanvas } from "../features/vision/VisionOverlayCanvas";

interface CameraStreamProps {
  cameraId: string;
  streamReady?: boolean;
  streamUrl?: string | null;
  playbackUrl?: string | null; // Compatibility only; production viewing uses MJPEG.
  className?: string;
  onError?: () => void;
  showBoxes?: boolean;
  result?: CameraVisionResult | null;
}

export function CameraStream({ cameraId, streamReady, streamUrl, className, onError, showBoxes=false, result=null }: CameraStreamProps) {
  const [generation,setGeneration]=useState(0);
  const retryAttempt=useRef(0);
  const retryTimer=useRef<number|null>(null);
  const imageRef=useRef<HTMLImageElement>(null);

  useEffect(()=>{
    retryAttempt.current=0;
    setGeneration(0);
    if(retryTimer.current!==null)window.clearTimeout(retryTimer.current);
    retryTimer.current=null;
    return()=>{if(retryTimer.current!==null)window.clearTimeout(retryTimer.current)};
  },[cameraId,streamUrl,streamReady]);

  const handleError=()=>{
    onError?.();
    if(!streamReady||!streamUrl||retryTimer.current!==null)return;
    const delays=[500,1000,2000,4000,5000];
    const delay=delays[Math.min(retryAttempt.current,delays.length-1)];
    retryAttempt.current+=1;
    retryTimer.current=window.setTimeout(()=>{retryTimer.current=null;setGeneration((value)=>value+1)},delay);
  };
  const handleLoad=()=>{retryAttempt.current=0};

  if (streamReady && streamUrl) {
    const separator=streamUrl.includes("?")?"&":"?";
    const configured=`${streamUrl}${separator}generation=${generation}`;
    const streamClassName=["camera-stream-image",className].filter(Boolean).join(" ");
    return <span className="camera-media-layer">
      <img ref={imageRef} className={streamClassName} src={configured} alt={`Luồng trực tiếp ${cameraId}`} onError={handleError} onLoad={handleLoad} />
      <VisionOverlayCanvas mediaRef={imageRef} result={result} visible={showBoxes} />
    </span>;
  }
  return null;
}
