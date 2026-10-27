"use client";

import { useActionState } from "react";
import { login, type LoginState } from "./actions";

const initial: LoginState = { error: null };

export function LoginForm() {
  const [state, action, pending] = useActionState(login, initial);
  return (
    <form className="chat-login" action={action}>
      <label htmlFor="chat-code">邀请码</label>
      <input
        id="chat-code"
        name="code"
        type="password"
        autoComplete="off"
        required
        maxLength={200}
        aria-describedby={state.error ? "chat-login-error" : undefined}
        aria-invalid={state.error ? true : undefined}
      />
      {state.error ? (
        <p className="chat-alert" id="chat-login-error" role="alert">
          {state.error}
        </p>
      ) : null}
      <button className="button button-primary" type="submit" disabled={pending}>
        {pending ? "正在核对…" : "进入问答"}
      </button>
    </form>
  );
}
