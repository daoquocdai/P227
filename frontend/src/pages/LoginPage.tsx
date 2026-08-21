import { Eye, EyeOff, HeartHandshake, LockKeyhole, ShieldCheck, UserRound } from "lucide-react";
import { useState, type FormEvent } from "react";
import { changePassword, login, type AuthUser } from "../api/auth";
import "./login.css";

export default function LoginPage({ onAuthenticated, user }: {
  onAuthenticated: (user: AuthUser) => void;
  user?: AuthUser | null;
}) {
  const [visible, setVisible] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      if (user?.force_password_change) {
        onAuthenticated(await changePassword(String(form.get("password"))));
      } else {
        onAuthenticated(await login(
          String(form.get("identity")),
          String(form.get("password")),
          form.get("remember") === "on",
        ));
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể đăng nhập");
    } finally {
      setLoading(false);
    }
  };
  return <main className="login-page">
    <section className="login-brand-panel"><div className="login-brand"><HeartHandshake /><strong>An Tâm</strong></div><div><p>AN TOÀN TẠI GIA</p><h1>An tâm hơn khi công nghệ luôn đồng hành.</h1><span>Camera AI xử lý cục bộ, bảo vệ gia đình và quyền riêng tư.</span><aside><ShieldCheck /><b>Video thô không được gửi lên cloud.</b></aside></div></section>
    <section className="login-form-panel"><form className="login-card" onSubmit={submit}><header><small>{user?.force_password_change ? "BẢO MẬT TÀI KHOẢN" : "CHÀO MỪNG TRỞ LẠI"}</small><h2>{user?.force_password_change ? "Đổi mật khẩu" : "Đăng nhập"}</h2></header>{error && <p className="login-error" role="alert">{error}</p>}{!user?.force_password_change && <label><span>Email</span><div><UserRound /><input name="identity" autoComplete="username" required autoFocus /></div></label>}<label><span>{user?.force_password_change ? "Mật khẩu mới" : "Mật khẩu"}</span><div><LockKeyhole /><input name="password" type={visible ? "text" : "password"} minLength={user?.force_password_change ? 8 : 1} autoComplete={user?.force_password_change ? "new-password" : "current-password"} required /><button type="button" onClick={() => setVisible(!visible)} aria-label={visible ? "Ẩn mật khẩu" : "Hiện mật khẩu"}>{visible ? <EyeOff /> : <Eye />}</button></div></label>{!user?.force_password_change && <label className="remember"><input name="remember" type="checkbox" /> Ghi nhớ đăng nhập</label>}<button className="login-submit" disabled={loading}>{loading ? "Đang xử lý…" : user?.force_password_change ? "Lưu mật khẩu mới" : "Đăng nhập"}</button></form></section>
  </main>;
}
