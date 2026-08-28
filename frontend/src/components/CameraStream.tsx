import { useEffect, useRef, useState } from "react";

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
  const [generation,setGeneration]=useState(0);
  const retryAttempt=useRef(0);
  const retryTimer=useRef<number|null>(null);

  useEffect(()=>{
    retryAttempt.current=0;
    setGeneration(0);
    if(retryTimer.current!==null)window.clearTimeout(retryTimer.current);
    retryTimer.current=null;
    return()=>{if(retryTimer.current!==null)window.clearTimeout(retryTimer.current)};
  },[cameraId,streamUrl,streamReady,showBoxes,showIdentity]);

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
    const configured=`${streamUrl}${separator}boxes=${showBoxes}&identity=${showIdentity}&generation=${generation}`;
    const streamClassName=["camera-stream-image",className].filter(Boolean).join(" ");
    return <img className={streamClassName} src={configured} alt={`Luồng trực tiếp ${cameraId}`} onError={handleError} onLoad={handleLoad} />;
  }
  return null;
}
