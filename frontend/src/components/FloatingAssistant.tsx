import { Bell, Camera, HeartHandshake, HelpCircle, Send, ShieldCheck, Sparkles, UsersRound, Wifi, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { initialAlerts } from "../features/alerts/alertMockData";
import type { AlertStatus } from "../features/alerts/alert.types";
import { answerAntamQuestion } from "./antamAssistantEngine";

type CompanionMessage={id:string;role:"user"|"assistant";text:string;time:string;suggestions?:string[]};
const initialQuestions=["Cách thêm camera?","Vì sao AI phát hiện té ngã?","Camera ngoại tuyến phải làm gì?","Hôm nay là ngày bao nhiêu?"];

export default function FloatingAssistant() {
  const [open, setOpen] = useState(false);
  const [peekVisible,setPeekVisible]=useState(false);
  const [helpOpen,setHelpOpen]=useState(false); const [question,setQuestion]=useState(""); const [typing,setTyping]=useState(false);
  const [messages,setMessages]=useState<CompanionMessage[]>(()=>{try{const saved=JSON.parse(localStorage.getItem("antam_companion_messages")||"[]");return Array.isArray(saved)?saved:[]}catch{return []}}); const conversationRef=useRef<HTMLDivElement>(null);
  const [statusOverrides, setStatusOverrides] = useState<Record<string, AlertStatus>>({});
  const [position,setPosition]=useState<{x:number;y:number}|null>(()=>{try{const saved=JSON.parse(localStorage.getItem("antam_pet_position")||"null");return Number.isFinite(saved?.x)&&Number.isFinite(saved?.y)?saved:null}catch{return null}});
  const [dragging,setDragging]=useState(false); const skipClickRef=useRef(false); const dragRef=useRef({pointerId:-1,startX:0,startY:0,originX:0,originY:0,moved:false});
  useEffect(() => {
    const syncAlertStatus = (event: Event) => {
      const detail = (event as CustomEvent<{ id: string; status: AlertStatus }>).detail;
      setStatusOverrides((current) => ({ ...current, [detail.id]: detail.status }));
    };
    window.addEventListener("antam:alert-status", syncAlertStatus);
    return () => window.removeEventListener("antam:alert-status", syncAlertStatus);
  }, []);
  useEffect(()=>{const keepInViewport=()=>setPosition(current=>current?{x:Math.max(8,Math.min(current.x,window.innerWidth-(window.innerWidth<=600?58:66)-8)),y:Math.max(8,Math.min(current.y,window.innerHeight-(window.innerWidth<=600?58:66)-8))}:current);keepInViewport();window.addEventListener("resize",keepInViewport);return()=>window.removeEventListener("resize",keepInViewport)},[]);
  useEffect(()=>{localStorage.setItem("antam_companion_messages",JSON.stringify(messages));const area=conversationRef.current;if(area)requestAnimationFrame(()=>area.scrollTo({top:area.scrollHeight,behavior:"smooth"}))},[messages,typing]);
  const urgentAlerts = initialAlerts.filter((alert) => {const occurredAt=new Date(alert.occurredAt),today=new Date();const isToday=occurredAt.getFullYear()===today.getFullYear()&&occurredAt.getMonth()===today.getMonth()&&occurredAt.getDate()===today.getDate();return isToday&&["high", "critical"].includes(alert.severity) && ["pending", "need_help"].includes(statusOverrides[alert.id] ?? alert.status)});
  const urgentAlert = urgentAlerts[0];
  useEffect(()=>{if(!urgentAlert||open)return;setPeekVisible(true);const timer=window.setTimeout(()=>setPeekVisible(false),8000);return()=>window.clearTimeout(timer)},[urgentAlert?.id,open]);

  const navigate = (path: string) => {
    window.history.pushState({}, "", path);
    window.dispatchEvent(new PopStateEvent("popstate"));
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
    setOpen(false);
    setPeekVisible(false);
  };
  const onPointerDown=(event:ReactPointerEvent<HTMLButtonElement>)=>{if(event.button!==0)return;skipClickRef.current=false;const rect=event.currentTarget.getBoundingClientRect();dragRef.current={pointerId:event.pointerId,startX:event.clientX,startY:event.clientY,originX:rect.left,originY:rect.top,moved:false};event.currentTarget.setPointerCapture(event.pointerId)};
  const onPointerMove=(event:ReactPointerEvent<HTMLButtonElement>)=>{const drag=dragRef.current;if(drag.pointerId!==event.pointerId)return;const dx=event.clientX-drag.startX,dy=event.clientY-drag.startY;if(!drag.moved&&Math.hypot(dx,dy)<5)return;drag.moved=true;setDragging(true);setOpen(false);const size=window.innerWidth<=600?58:66;setPosition({x:Math.max(8,Math.min(drag.originX+dx,window.innerWidth-size-8)),y:Math.max(8,Math.min(drag.originY+dy,window.innerHeight-size-8))})};
  const finishDrag=(event:ReactPointerEvent<HTMLButtonElement>, cancelled=false)=>{const drag=dragRef.current;if(drag.pointerId!==event.pointerId)return;const moved=drag.moved;drag.pointerId=-1;drag.moved=false;skipClickRef.current=moved&&!cancelled;setDragging(false);if(event.currentTarget.hasPointerCapture(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId);if(moved)setPosition(current=>{if(current)localStorage.setItem("antam_pet_position",JSON.stringify(current));return current})};
  const onPointerUp=(event:ReactPointerEvent<HTMLButtonElement>)=>finishDrag(event);
  const onPointerCancel=(event:ReactPointerEvent<HTMLButtonElement>)=>finishDrag(event,true);
  const onLostPointerCapture=(event:ReactPointerEvent<HTMLButtonElement>)=>finishDrag(event,true);
  const petX=position?.x??window.innerWidth-100; const petY=position?.y??window.innerHeight-140; const openRight=petX<350; const openBelow=petY<360;
  const ask=(value=question)=>{const text=value.trim();if(!text||typing)return;const time=()=>new Date().toLocaleTimeString("vi-VN",{hour:"2-digit",minute:"2-digit"});setMessages(items=>[...items,{id:`user-${Date.now()}`,role:"user",text,time:time()}]);setQuestion("");setTyping(true);window.setTimeout(()=>{const lower=text.toLocaleLowerCase("vi");const suggestions=lower.includes("camera")?["Cách kiểm tra Wi-Fi?","Mở camera ở đâu?","Xem lịch sử camera"]:lower.includes("té ngã")||lower.includes("cảnh báo")?["Độ tin cậy 91% là gì?","Khi nào xác nhận an toàn?","Khi nào cần hỗ trợ?"]:["Cách thêm camera?","Ý nghĩa cảnh báo té ngã?","Xem lịch sử camera"];setMessages(items=>[...items,{id:`assistant-${Date.now()}`,role:"assistant",text:answerAntamQuestion(text),time:time(),suggestions}]);setTyping(false)},650)};

  return <div style={position?{left:position.x,top:position.y,right:"auto",bottom:"auto"}:undefined} className={`floating-assistant companion-root ${open ? "is-open" : ""} ${urgentAlerts.length > 0 ? "has-urgent-alert" : ""} ${dragging?"is-dragging":""} ${openRight?"open-right":""} ${openBelow?"open-below":""}`}>
    {peekVisible&&!open&&urgentAlert&&<section className="companion-peek" aria-live="polite"><header><span><HeartHandshake/></span><strong>An Tâm</strong></header><p>{urgentAlert.title} vừa được phát hiện tại {urgentAlert.location.toLocaleLowerCase("vi")}.</p><div><button className="peek-primary" onClick={()=>navigate(`/alerts/${encodeURIComponent(urgentAlert.id)}`)}>Xem ngay</button><button onClick={()=>setPeekVisible(false)}>Để sau</button></div></section>}
    {open&&<><button className="companion-backdrop" aria-label="Đóng trợ lý" onClick={()=>setOpen(false)}/><aside className="companion-panel" aria-label="Trợ lý thông minh An Tâm">
      <header><span className="companion-avatar"><HeartHandshake/></span><div><strong>An Tâm</strong><small><i/> Đang hỗ trợ</small></div><button onClick={()=>setOpen(false)} aria-label="Đóng"><X/></button></header>
      <div className="companion-body"><section className="companion-intro"><Sparkles/><div><strong>Chào Minh</strong><p>Mình đã tổng hợp những điều đáng chú ý trong ngôi nhà.</p></div></section>
        {urgentAlert?<CompanionCard tone="danger" icon={Bell} title="Cảnh báo mới" description={`${urgentAlert.title} · ${urgentAlert.location} · ${urgentAlert.time}`} action="Kiểm tra ngay" onAction={()=>navigate(`/alerts/${encodeURIComponent(urgentAlert.id)}`)}/>:<CompanionCard tone="safe" icon={ShieldCheck} title="Không có cảnh báo hôm nay" description="Mọi khu vực đang được theo dõi ổn định."/>}
        <CompanionCard icon={Camera} title="Camera" description="3 camera đang sẵn sàng để kiểm tra." action="Mở camera" onAction={()=>navigate("/camera")}/>
        <CompanionCard icon={UsersRound} title="Người thân" description="Danh bạ hỗ trợ gia đình luôn sẵn sàng." action="Xem danh bạ" onAction={()=>navigate("/relatives")}/>
        <CompanionCard icon={Wifi} title="Gợi ý" description="Kiểm tra camera định kỳ để bảo đảm hình ảnh luôn rõ ràng."/>
        <CompanionCard icon={HelpCircle} title="Trợ giúp An Tâm" description="Hỏi về cách sử dụng hoặc ý nghĩa cảnh báo." action={helpOpen?"Thu gọn":"Mở trợ giúp"} onAction={()=>setHelpOpen(value=>!value)}/>
        {helpOpen&&<section className="companion-help companion-conversation">{messages.length===0&&<div className="companion-welcome"><strong>💡 Tôi có thể giúp bạn</strong><div className="companion-help-suggestions">{initialQuestions.map(item=><button key={item} onClick={()=>ask(item)}>{item}</button>)}</div></div>}<div className="companion-help-messages" ref={conversationRef}>{messages.map((message,index)=><div key={message.id} className={`companion-message ${message.role}`}>{message.role==="assistant"&&<span className="companion-message-avatar"><HeartHandshake/></span>}<div><header>{message.role==="assistant"&&<strong>An Tâm</strong>}<time>{message.time}</time></header><p>{message.text}</p>{message.role==="assistant"&&index===messages.length-1&&message.suggestions&&<section className="companion-followups"><small>Có thể bạn muốn hỏi</small><div>{message.suggestions.map(item=><button key={item} onClick={()=>ask(item)}>{item}</button>)}</div></section>}</div></div>)}{typing&&<div className="companion-message assistant typing"><span className="companion-message-avatar"><HeartHandshake/></span><div><header><strong>An Tâm</strong></header><p><i/><i/><i/></p></div></div>}</div><div className="companion-help-input"><input value={question} disabled={typing} onChange={event=>setQuestion(event.target.value)} onKeyDown={event=>{if(event.key==="Enter")ask()}} placeholder="Hỏi An Tâm về hệ thống..."/><button disabled={typing||!question.trim()} onClick={()=>ask()}><Send/></button></div></section>}
      </div>
    </aside></>}
    <button className="assistant-pet" onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerCancel} onLostPointerCapture={onLostPointerCapture} onClick={(event) => {if(skipClickRef.current&&event.detail!==0){skipClickRef.current=false;return}skipClickRef.current=false;setPeekVisible(false);setOpen((value) => !value)}} aria-label={open ? "Đóng trợ lý An Tâm" : "Mở trợ lý An Tâm"} aria-expanded={open}>
      <span className="pet-glow" />
      <span className="pet-body"><HeartHandshake /><i className="pet-eye left" /><i className="pet-eye right" /></span>
      <span className="pet-status" />
      {urgentAlerts.length > 0 && <span className="pet-alert-badge">{urgentAlerts.length}</span>}
    </button>
  </div>;
}

function CompanionCard({icon:Icon,title,description,action,onAction,tone=""}:{icon:typeof Camera;title:string;description:string;action?:string;onAction?:()=>void;tone?:string}){return <article className={`companion-card ${tone}`}><span><Icon/></span><div><strong>{title}</strong><p>{description}</p>{action&&<button onClick={onAction}>{action}</button>}</div></article>}
