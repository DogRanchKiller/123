"use client";

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

const unavailable = "账号服务尚未接入，本次未登录或注册，也未发送验证码。";

export function AuthTrigger() {
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [method, setMethod] = useState<"email" | "phone">("email");
  const [message, setMessage] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  useEffect(() => {
    if (open) dialog.current?.showModal();
    else dialog.current?.close();
  }, [open]);

  function close() {
    setOpen(false);
    setMessage("");
    setShowPassword(false);
    trigger.current?.focus();
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    if (method === "email" && mode === "register" && values.get("password") !== values.get("confirmation")) {
      setMessage("两次输入的密码不一致。");
      return;
    }
    setMessage(unavailable);
  }

  function keepFocus(event: KeyboardEvent<HTMLDialogElement>) {
    if (event.key !== "Tab") return;
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled), [tabindex='0']"));
    const first=items[0], last=items.at(-1);
    if(event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if(!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }

  return <>
    <button ref={trigger} className="button auth-trigger" onClick={() => setOpen(true)}>登录 / 注册</button>
    <dialog ref={dialog} className="auth-dialog" aria-labelledby="auth-title" onKeyDown={keepFocus}
      onCancel={(event) => { event.preventDefault(); close(); }}
      onClose={() => { setOpen(false); trigger.current?.focus(); }}>
      {open && <div className="auth-content">
        <button className="auth-close button" aria-label="关闭登录窗口" onClick={close}>×</button>
        <p className="eyebrow">YOUR NEXT MATCH STARTS HERE</p>
        <h2 id="auth-title">{mode === "login" ? "欢迎回到绿茵观察" : "开启你的比赛视角"}</h2>
        <p className="auth-intro">前端预览 · 账号服务尚未接入，查看预测无需登录。</p>
        <div className="auth-tabs" aria-label="账号操作">
          {(["login", "register"] as const).map((value) => <button key={value} type="button" aria-pressed={mode === value}
            onClick={() => { setMode(value); setMessage(""); }}>{value === "login" ? "登录" : "注册"}</button>)}
        </div>
        <div className="auth-methods" aria-label="登录方式">
          {(["email", "phone"] as const).map((value) => <button key={value} type="button" aria-pressed={method === value}
            onClick={() => { setMethod(value); setMessage(""); }}>{value === "email" ? "邮箱密码" : "手机验证码"}</button>)}
        </div>
        <form key={`${mode}-${method}`} onSubmit={submit}>
          {method === "email" ? <>
            <label>邮箱<input name="email" type="email" autoComplete="email" placeholder="you@example.com" required maxLength={254} /></label>
            <label>密码<span className="auth-password"><input aria-label="密码" name="password" type={showPassword ? "text" : "password"}
              autoComplete={mode === "register" ? "new-password" : "current-password"} minLength={8} maxLength={128} placeholder="至少 8 位字符" required />
              <button type="button" aria-label={showPassword ? "隐藏密码" : "显示密码"} onClick={() => setShowPassword(!showPassword)}>{showPassword ? "隐藏" : "显示"}</button></span></label>
            {mode === "register" && <label>确认密码<input aria-label="确认密码" name="confirmation" type={showPassword ? "text" : "password"} autoComplete="new-password" minLength={8} maxLength={128} required /></label>}
            {mode === "login" && <button type="button" className="text-link" onClick={() => setMessage("找回密码服务尚未接入，未发送邮件。")}>忘记密码？</button>}
          </> : <>
            <label>手机号<input name="phone" type="tel" autoComplete="tel" inputMode="tel" pattern="1[3-9][0-9]{9}" placeholder="中国大陆 11 位手机号" required /></label>
            <label>验证码<span className="auth-password"><input name="code" autoComplete="one-time-code" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} placeholder="6 位验证码" required />
              <button type="button" onClick={() => setMessage("短信服务尚未接入，未发送验证码。")}>获取验证码</button></span></label>
          </>}
          <button className="button button-primary auth-submit" type="submit">{mode === "login" ? "登录" : "注册"}</button>
        </form>
        {message && <p className="auth-message" role="status">{message}</p>}
        <p className="fine-print">不保存密码或验证码，不会建立登录会话。</p>
      </div>}
    </dialog>
  </>;
}
