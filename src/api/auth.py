from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from src.services.auth_service import AuthenticationError, InactiveAccountError, auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"])
def bearer_token(authorization: str | None = Header(default=None)): return authorization[7:] if authorization and authorization.startswith("Bearer ") else None
def current_user(token: str | None = Depends(bearer_token)):
    try: return auth_service.authenticate(token)
    except InactiveAccountError as exc: raise HTTPException(403, "Tài khoản đã bị vô hiệu hoá. Liên hệ quản trị viên.") from exc
    except AuthenticationError as exc: raise HTTPException(401, "Phiên đăng nhập không hợp lệ") from exc
def require_permission(permission: str):
    def dependency(user=Depends(current_user)):
        if user["force_password_change"]: raise HTTPException(403, "Bạn phải đổi mật khẩu trước khi tiếp tục")
        if not auth_service.allowed(user, permission): raise HTTPException(403, "Bạn không có quyền thực hiện thao tác này")
        return user
    return dependency
def require_admin(user=Depends(current_user)):
    if user["force_password_change"]: raise HTTPException(403, "Bạn phải đổi mật khẩu trước khi tiếp tục")
    if user["role"] != "admin": raise HTTPException(403, "Chỉ quản trị viên được thực hiện thao tác này")
    return user
class LoginRequest(BaseModel):
    identity: str = Field(min_length=1,max_length=255); password: str = Field(min_length=1,max_length=512); remember: bool=False
class PasswordChange(BaseModel): password: str = Field(min_length=8,max_length=128)
@router.post("/login")
async def login(data: LoginRequest):
    try:
        token,user=auth_service.login(data.identity,data.password,data.remember); return {"token":token,"user":user}
    except InactiveAccountError as exc: raise HTTPException(403,"Tài khoản đã bị vô hiệu hoá. Liên hệ quản trị viên.") from exc
    except AuthenticationError as exc: raise HTTPException(401,"Tên đăng nhập/Email hoặc mật khẩu không đúng") from exc
@router.get("/me")
async def me(user=Depends(current_user)): return user
@router.post("/change-password")
async def change_password(data:PasswordChange,user=Depends(current_user)): return auth_service.change_password(user["id"],data.password)
@router.post("/logout",status_code=204)
async def logout(token=Depends(bearer_token)): auth_service.logout(token)
