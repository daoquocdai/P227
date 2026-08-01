import type { AlertRecipient, CameraDetail, CameraEvent, EmergencyContact } from "./cameraDetail.types";
import { mockEvents } from "../../mocks/data/events";
export const cameraDetail: CameraDetail = { id:"camera-bedroom", name:"Camera phòng ngủ", room:"Phòng ngủ", status:"online", quality:"HD", lastUpdatedAt:"2026-07-30T17:16:00", videoUrl:"/videos/45353-448489443_medium.mp4", monitoringStatus:"active", safetyStatus:"safe" };
const cameraProfiles: Record<string, Pick<CameraDetail,"id"|"name"|"room"|"videoUrl"|"status">> = {
  "camera-bedroom": {id:"camera-bedroom",name:"Camera phòng ngủ",room:"Phòng ngủ",videoUrl:"/videos/45353-448489443_medium.mp4",status:"online"},
  "camera-living": {id:"camera-living",name:"Camera phòng khách",room:"Phòng khách",videoUrl:"/videos/76621-559757958.mp4",status:"online"},
  "camera-entrance": {id:"camera-entrance",name:"Camera cửa chính",room:"Cửa chính",videoUrl:"/videos/45353-448489443_medium.mp4",status:"online"},
  "camera-front": {id:"camera-front",name:"Camera sân trước",room:"Sân trước",videoUrl:"/videos/76621-559757958.mp4",status:"offline"},
};
export const getCameraDetail = (cameraId:string): CameraDetail => ({...cameraDetail,...(cameraProfiles[cameraId]??cameraProfiles["camera-bedroom"])});
export const emergencyContact: EmergencyContact = { id:"contact-minh", name:"Minh Nguyễn", relationship:"Người chăm sóc", maskedPhone:"09•• ••• 128" };
export const alertRecipients: AlertRecipient[] = [{id:"minh",name:"Minh Nguyễn",role:"Người chăm sóc chính",enabled:true},{id:"hong",name:"Hồng Anh",role:"Người thân",enabled:true},{id:"neighbor",name:"Hàng xóm hỗ trợ",role:"Liên hệ dự phòng",enabled:false}];
export const cameraEvents: CameraEvent[] = [
 {id:"e1",cameraId:"camera-bedroom",type:"fall_detection",title:"Có khả năng té ngã",description:"Camera ghi nhận tư thế bất thường và không có chuyển động rõ ràng trong khoảng 12 giây.",occurredAt:"09:25",dayGroup:"Hôm nay",severity:"high",status:"new",confidence:91,isRead:false},
 {id:"e2",cameraId:"camera-bedroom",type:"motion_detected",title:"Phát hiện chuyển động",description:"Có hoạt động được ghi nhận trong khu vực.",occurredAt:"08:40",dayGroup:"Hôm nay",severity:"info",status:"reviewed",confidence:96,isRead:true},
 {id:"e3",cameraId:"camera-bedroom",type:"camera_online",title:"Camera đã kết nối lại",description:"Gián đoạn kết nối trong khoảng 2 phút.",occurredAt:"07:15",dayGroup:"Hôm nay",severity:"info",status:"reviewed",isRead:true},
 {id:"e4",cameraId:"camera-bedroom",type:"motion_detected",title:"Phát hiện chuyển động",description:"Có chuyển động nhẹ gần cửa phòng.",occurredAt:"06:48",dayGroup:"Hôm nay",severity:"info",status:"reviewed",isRead:true},
 {id:"e5",cameraId:"camera-bedroom",type:"immobility",title:"Không phát hiện hoạt động",description:"Khu vực yên tĩnh trong 45 phút.",occurredAt:"23:10",dayGroup:"Hôm qua",severity:"warning",status:"reviewed",isRead:true},
 {id:"e6",cameraId:"camera-bedroom",type:"motion_detected",title:"Có hoạt động trong khu vực",description:"Camera ghi nhận chuyển động nhẹ.",occurredAt:"21:32",dayGroup:"Hôm qua",severity:"info",status:"reviewed",isRead:true},
 {id:"e7",cameraId:"camera-bedroom",type:"motion_detected",title:"Chuyển động bất thường",description:"Hoạt động kéo dài hơn thường lệ.",occurredAt:"19:08",dayGroup:"Hôm qua",severity:"warning",status:"safe",confidence:72,isRead:true},
 {id:"e8",cameraId:"camera-bedroom",type:"monitoring_paused",title:"Đã tạm dừng giám sát",description:"Minh Nguyễn tạm dừng trong 15 phút.",occurredAt:"14:20",dayGroup:"Hôm qua",severity:"info",status:"reviewed",isRead:true},
 {id:"e9",cameraId:"camera-bedroom",type:"monitoring_resumed",title:"Đã tiếp tục giám sát",description:"Hệ thống hoạt động bình thường trở lại.",occurredAt:"14:35",dayGroup:"Hôm qua",severity:"info",status:"reviewed",isRead:true},
 {id:"e10",cameraId:"camera-bedroom",type:"camera_offline",title:"Camera mất kết nối",description:"Camera gián đoạn trong khoảng 1 phút.",occurredAt:"22:04",dayGroup:"28 tháng 7",severity:"warning",status:"reviewed",isRead:true},
 {id:"e11",cameraId:"camera-bedroom",type:"camera_online",title:"Camera hoạt động trở lại",description:"Kết nối đã được khôi phục.",occurredAt:"22:05",dayGroup:"28 tháng 7",severity:"info",status:"reviewed",isRead:true},
 {id:"e12",cameraId:"camera-bedroom",type:"motion_detected",title:"Khu vực có hoạt động",description:"Camera ghi nhận chuyển động bình thường.",occurredAt:"20:16",dayGroup:"28 tháng 7",severity:"info",status:"reviewed",confidence:98,isRead:true}
];
const sourceCameraIds: Record<string,string> = {
  "camera-bedroom":"cam-bedroom",
  "camera-living":"cam-living",
  "camera-entrance":"cam-entrance",
  "camera-front":"cam-front",
};

const eventDayGroup=(occurredAt:string):CameraEvent["dayGroup"]=>{
  const eventDate=new Date(occurredAt); const today=new Date();
  const eventDay=new Date(eventDate.getFullYear(),eventDate.getMonth(),eventDate.getDate()).getTime();
  const currentDay=new Date(today.getFullYear(),today.getMonth(),today.getDate()).getTime();
  const dayDifference=Math.round((currentDay-eventDay)/86_400_000);
  return dayDifference===0?"Hôm nay":dayDifference===1?"Hôm qua":"28 tháng 7";
};

export const getCameraEvents = (cameraId:string): CameraEvent[] => mockEvents
  .filter(event=>event.cameraId===sourceCameraIds[cameraId])
  .map(event=>({
    id:event.id,
    cameraId,
    type:event.eventType==="unknown_person"?"unknown_person":"fall_detection",
    title:event.description,
    description:event.fall
      ? `Camera ghi nhận tư thế bất thường và không có chuyển động rõ ràng trong khoảng ${event.fall.immobileSeconds} giây.`
      : event.description,
    occurredAt:new Date(event.occurredAt).toLocaleTimeString("vi-VN",{hour:"2-digit",minute:"2-digit"}),
    dayGroup:eventDayGroup(event.occurredAt),
    severity:event.severity==="critical"?"high":event.severity,
    status:event.status==="pending_review"?"new":event.status==="needs_attention"?"need_help":event.status==="false_alarm"?"false_alarm":event.status==="resolved"?"safe":"reviewed",
    confidence:event.fall?Math.round(event.fall.confidence*100):undefined,
    isRead:event.status!=="pending_review",
  }));
