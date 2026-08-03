import { AlertTriangle, Camera, CameraOff, ChevronLeft, ChevronRight, Expand, Info, ShieldCheck, Video, Volume2, VolumeX, Wifi } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import "./cameraViewer.css";
import { getCameraEvents } from "../features/camera-detail/cameraDetail.mock";

type Feed = { id:string; cameraId:string; name:string; room:string; kind:"webcam"|"video"|"offline"; src:string; lastSeen?:string };
const feeds: Feed[] = [
  {id:"bedroom",cameraId:"camera-bedroom",name:"Camera phòng ngủ",room:"Phòng ngủ",kind:"video",src:"/videos/45353-448489443_medium.mp4"},
  {id:"living",cameraId:"camera-living",name:"Camera phòng khách",room:"Phòng khách",kind:"video",src:"/videos/76621-559757958.mp4"},
  {id:"entrance",cameraId:"camera-entrance",name:"Camera cửa chính",room:"Cửa chính",kind:"video",src:"/videos/45353-448489443_medium.mp4"},
  {id:"front",cameraId:"camera-front",name:"Camera sân trước",room:"Sân trước",kind:"offline",src:"/videos/76621-559757958.mp4",lastSeen:"09:12"},
];
export default function CameraPage(){
  const [selectedId,setSelectedId]=useState(feeds[0].id); const [muted,setMuted]=useState(true); const [clock,setClock]=useState(new Date()); const [webcamActive,setWebcamActive]=useState(false); const [webcamError,setWebcamError]=useState("");
  const viewerRef=useRef<HTMLDivElement>(null); const videoRef=useRef<HTMLVideoElement>(null); const selectorRef=useRef<HTMLDivElement>(null); const streamRef=useRef<MediaStream|null>(null);
  const selected=feeds.find(feed=>feed.id===selectedId)??feeds[0];
  const todayEvents=getCameraEvents(selected.cameraId).filter(event=>event.dayGroup==="Hôm nay");
  useEffect(()=>{const timer=window.setInterval(()=>setClock(new Date()),1000);return()=>window.clearInterval(timer)},[]);
  useEffect(()=>()=>streamRef.current?.getTracks().forEach(track=>track.stop()),[]);
  const startWebcam=async()=>{try{const stream=await navigator.mediaDevices.getUserMedia({video:true,audio:false});streamRef.current=stream;if(videoRef.current){videoRef.current.srcObject=stream;await videoRef.current.play()}setWebcamActive(true);setWebcamError("")}catch{setWebcamError("Chưa được cấp quyền camera")}};
  const fullscreen=async()=>{if(document.fullscreenElement)await document.exitFullscreen();else await viewerRef.current?.requestFullscreen()};
  const capture=()=>{const video=videoRef.current;if(!video||!video.videoWidth)return;const canvas=document.createElement("canvas");canvas.width=video.videoWidth;canvas.height=video.videoHeight;canvas.getContext("2d")?.drawImage(video,0,0);const link=document.createElement("a");link.href=canvas.toDataURL("image/jpeg",.9);link.download=`${selected.id}-${Date.now()}.jpg`;link.click()};
  const detail=()=>{window.history.pushState({},"",`/camera/${selected.cameraId}`);window.dispatchEvent(new PopStateEvent("popstate"))};
  const navigate=(path?:string)=>{if(!path)return;window.history.pushState({},"",path);window.dispatchEvent(new PopStateEvent("popstate"))};
  const moveCarousel=(direction:-1|1)=>selectorRef.current?.scrollBy({left:direction*220,behavior:"smooth"});
  return <section className="smart-camera-page">
    <header className="smart-camera-heading"><div><p>Không gian của bạn</p><h1>Camera</h1></div><span><ShieldCheck/> Mọi khu vực đang được bảo vệ</span></header>
    <div className="smart-viewer-shell">
      <div className="smart-camera-viewer" ref={viewerRef} key={selected.id}>
        {selected.kind==="video"&&(
          <video ref={videoRef} src={selected.src} autoPlay loop playsInline muted={muted}/>
        )}
        {selected.kind==="webcam"&&<video ref={videoRef} autoPlay playsInline muted className="mirror"/>}
        {selected.kind==="webcam"&&!webcamActive&&<button className="smart-webcam-placeholder" onClick={startWebcam}><Camera/><strong>{webcamError||"Bật camera trong nhà"}</strong><span>Không sử dụng micro</span></button>}
        {selected.kind==="offline"&&<div className="smart-camera-offline"><CameraOff/><strong>Camera đang ngoại tuyến</strong><span>Hình ảnh gần nhất lúc 09:12</span></div>}
        <div className="smart-viewer-top"><span className={`smart-live ${selected.kind==="offline"?"offline":""}`}><i/><span className="smart-live-label">{selected.kind==="offline"?"Ngoại tuyến":"Trực tiếp"}</span></span></div>
        <div className="smart-viewer-bottom"><div><strong>{selected.name}</strong><span>{selected.room}</span></div><time>{clock.toLocaleTimeString("vi-VN",{hour12:false})}</time></div>
      </div>

      <div className="camera-selector-wrap">
        <header><h2>Camera khác</h2><div><button onClick={()=>moveCarousel(-1)} aria-label="Camera trước"><ChevronLeft/></button><button onClick={()=>moveCarousel(1)} aria-label="Camera tiếp theo"><ChevronRight/></button></div></header>
        <div className="camera-selector" ref={selectorRef} aria-label="Chọn camera">{feeds.map(feed=><button key={feed.id} className={selected.id===feed.id?"active":""} onClick={()=>setSelectedId(feed.id)}><VideoThumbnail feed={feed}/><span className="thumbnail-camera-info"><strong>{feed.name}</strong><small><i className={feed.kind==="offline"?"offline":""}/>{feed.kind==="offline"?"Ngoại tuyến":"Trực tuyến"}</small></span></button>)}</div>
        <div className="camera-carousel-dots" aria-hidden="true">{feeds.map(feed=><i key={feed.id} className={selected.id===feed.id?"active":""}/>)}</div>
      </div>

      <section className="smart-camera-actions"><button disabled={selected.kind==="offline"} onClick={capture}><Camera/><span><strong>Chụp ảnh</strong><small>Lưu khung hình hiện tại</small></span></button><button disabled={selected.kind==="offline"} onClick={fullscreen} className="primary"><Expand/><span><strong>Toàn màn hình</strong><small>Xem camera rõ hơn</small></span></button><button disabled={selected.kind==="offline"} onClick={()=>setMuted(value=>!value)}>{muted?<VolumeX/>:<Volume2/>}<span><strong>{muted?"Bật âm thanh":"Tắt âm thanh"}</strong><small>Âm thanh camera</small></span></button><button onClick={detail}><Info/><span><strong>Chi tiết camera</strong><small>Trạng thái và lịch sử</small></span></button></section>

      <section className="viewer-recent-events"><header><div><h2>Sự kiện hôm nay</h2><p>Chỉ hiển thị hoạt động trong ngày của {selected.name.toLocaleLowerCase("vi")}.</p></div><button onClick={detail}>Xem lịch sử <ChevronRight/></button></header><div>{todayEvents.length?todayEvents.map(event=>{const Icon=event.type==="fall_detection"?AlertTriangle:event.type==="camera_online"||event.type==="camera_offline"?Wifi:Video;const tone=event.severity==="high"?"danger":event.status==="safe"?"safe":"info";return <button className={`viewer-event-row ${tone}`} key={event.id} onClick={()=>navigate(`/camera/${encodeURIComponent(selected.cameraId)}?event=${encodeURIComponent(event.id)}`)}><time>{event.occurredAt}</time><span><Icon/></span><div><strong>{event.title}</strong><small>{event.description}</small></div><ChevronRight/></button>}):<p className="viewer-events-empty">Hôm nay camera này chưa ghi nhận sự kiện.</p>}</div></section>
    </div>
  </section>;
}

function VideoThumbnail({feed}:{feed:Feed}){
  const previewRef=useRef<HTMLVideoElement>(null);
  useEffect(()=>{if(feed.kind!=="offline")return;const video=previewRef.current;if(!video)return;const showLastFrame=()=>{video.currentTime=Math.min(1,video.duration||1);video.pause()};video.addEventListener("loadedmetadata",showLastFrame);return()=>video.removeEventListener("loadedmetadata",showLastFrame)},[feed.kind]);
  return <span className={`video-thumbnail ${feed.kind==="offline"?"offline":""}`}>
    <video ref={previewRef} src={feed.src} autoPlay={feed.kind!=="offline"} loop={feed.kind!=="offline"} muted playsInline preload="metadata"/>
    <span className={`thumbnail-status ${feed.kind==="offline"?"offline":""}`}><i/>{feed.kind==="offline"?"Ngoại tuyến":"Trực tiếp"}</span>
    {feed.kind==="offline"&&<span className="thumbnail-offline-copy"><strong>Camera ngoại tuyến</strong><small>Lần cuối: {feed.lastSeen}</small></span>}
    <span className="thumbnail-name">{feed.name}</span>
  </span>;
}
