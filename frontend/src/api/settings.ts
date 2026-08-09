import { apiClient } from "./client";

export type PermissionKey = "view_history" | "acknowledge_alert" | "resolve_alert" | "manage_cameras" | "manage_persons" | "manage_users";
export interface SettingsUser { id:string; name:string; email:string; role:"admin"|"caregiver"; active:boolean; created_at:string; permissions:Record<PermissionKey,boolean>; }
export interface SettingsCamera { id:string; name:string; location_label:string; operational_status:"connecting"|"online"|"offline"|"ended"|"error"; vision_status:string; last_seen_at?:string|null; is_active:boolean; vision_enabled:boolean; source_kind:string; }
export interface GeneralSettingsData { retention_days:7|30|90; stranger_threshold:number; fall_threshold:number; sensitive_enabled:boolean; sensitive_from:string; sensitive_to:string; }
export interface NotificationSettingsData { app:boolean; email:boolean; sms:boolean; level:"all"|"important"; grouped:boolean; quiet_enabled:boolean; quiet_from:string; quiet_to:string; }
export interface SettingsData { general:GeneralSettingsData; notifications:NotificationSettingsData; users:SettingsUser[]; cameras:SettingsCamera[]; }

export const getSettings = () => apiClient<SettingsData>("/settings");
export const saveGeneral = (data:GeneralSettingsData) => apiClient<GeneralSettingsData>("/settings/general",{method:"PATCH",body:JSON.stringify(data)});
export const saveNotifications = (data:NotificationSettingsData) => apiClient<NotificationSettingsData>("/settings/notifications",{method:"PATCH",body:JSON.stringify(data)});
export const createSettingsUser = (data:{name:string;email:string;role:"admin"|"caregiver"}) => apiClient<SettingsUser>("/settings/users",{method:"POST",body:JSON.stringify(data)});
export const setSettingsUserActive = (id:string,active:boolean) => apiClient<SettingsUser>(`/settings/users/${encodeURIComponent(id)}`,{method:"PATCH",body:JSON.stringify({active})});
export const setUserPermission = (id:string,key:PermissionKey,granted:boolean) => apiClient<SettingsUser>(`/settings/users/${encodeURIComponent(id)}/permissions/${key}`,{method:"PATCH",body:JSON.stringify({granted})});
export const setSettingsCameraActive = (id:string,active:boolean) => apiClient<SettingsData>(`/settings/cameras/${encodeURIComponent(id)}`,{method:"PATCH",body:JSON.stringify({active})});
export const setSettingsCameraVision = (id:string,vision_enabled:boolean) => apiClient<SettingsData>(`/settings/cameras/${encodeURIComponent(id)}`,{method:"PATCH",body:JSON.stringify({vision_enabled})});
