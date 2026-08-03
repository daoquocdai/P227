export type CameraStatus = "online" | "offline";
export type CameraEventType = "fall_detection" | "immobility" | "person_detected" | "unknown_person" | "member_recognized" | "camera_offline" | "camera_online" | "motion_detected" | "monitoring_paused" | "monitoring_resumed";
export type CameraEventSeverity = "info" | "warning" | "high";
export type CameraEventStatus = "new" | "reviewed" | "safe" | "false_alarm" | "need_help";
export interface CameraDetail { id:string; name:string; room:string; status:CameraStatus; quality:"HD"; lastUpdatedAt:string; videoUrl:string; monitoringStatus:"active"|"paused"; safetyStatus:"safe"|"attention"; }
export interface CameraEvent { id:string; cameraId:string; type:CameraEventType; title:string; description:string; occurredAt:string; dayGroup:"Hôm nay"|"Hôm qua"|"28 tháng 7"; severity:CameraEventSeverity; status:CameraEventStatus; confidence?:number; isRead:boolean; notes?:string; }
export interface EmergencyContact { id:string; name:string; relationship:string; maskedPhone:string; }
export interface AlertRecipient { id:string; name:string; role:string; enabled:boolean; }
export type HistoryFilter = "today"|"7days"|"30days"|"custom";
