import { apiClient, setAuthToken } from "./client";
import type { PermissionKey } from "./settings";
export type AuthUser={id:string;email:string;name:string;role:"admin"|"caregiver";active:boolean;force_password_change:boolean;permissions:Record<PermissionKey,boolean>};
export const login=async(identity:string,password:string,remember:boolean)=>{const value=await apiClient<{token:string;user:AuthUser}>("/auth/login",{method:"POST",body:JSON.stringify({identity,password,remember})});setAuthToken(value.token,remember);return value.user};
export const me=()=>apiClient<AuthUser>("/auth/me");
export const changePassword=(password:string)=>apiClient<AuthUser>("/auth/change-password",{method:"POST",body:JSON.stringify({password})});
export const logout=async()=>{try{await apiClient("/auth/logout",{method:"POST"})}finally{setAuthToken(null,false)}};
