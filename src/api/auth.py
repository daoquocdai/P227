from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from src.services.auth_service import AuthenticationError, InactiveAccountError, auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


def bearer_token(authorization: str | None = Header(default=None)) -> str | None:
    return authorization[7:] if authorization and authorization.startswith("Bearer ") else None


def current_user(token: str | None = Depends(bearer_token)) -> dict:
    try:
        return auth_service.authenticate(token)
    except InactiveAccountError as exc:
        raise HTTPException(403, "Tài khoản đã bị vô hiệu hoá") from exc
    except AuthenticationError as exc:
        raise HTTPException(401, "Phiên đăng nhập không hợp lệ") from exc


def require_admin(user: dict = Depends(current_user)) -> dict:
    if user["force_password_change"]:
        raise HTTPException(403, "Bạn phải đổi mật khẩu trước khi tiếp tục")
    if user["role"] != "admin":
        raise HTTPException(403, "Chỉ quản trị viên được xem thống kê hệ thống")
    return user


class LoginRequest(BaseModel):
    identity: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=512)
    remember: bool = False


class PasswordChange(BaseModel):
    password: str = Field(min_length=8, max_length=128)


@router.post("/login")
async def login(data: LoginRequest):
    try:
        token, user = auth_service.login(data.identity, data.password, data.remember)
        return {"token": token, "user": user}
    except InactiveAccountError as exc:
        raise HTTPException(403, "Tài khoản đã bị vô hiệu hoá") from exc
    except AuthenticationError as exc:
        raise HTTPException(401, "Email hoặc mật khẩu không đúng") from exc


@router.get("/me")
async def me(user: dict = Depends(current_user)):
    return user


@router.post("/change-password")
async def change_password(data: PasswordChange, user: dict = Depends(current_user)):
    return auth_service.change_password(user["id"], data.password)


@router.post("/logout", status_code=204)
async def logout(token: str | None = Depends(bearer_token)):
    auth_service.logout(token)
