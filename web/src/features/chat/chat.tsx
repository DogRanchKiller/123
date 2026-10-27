import { EmptyState } from "@/components/presentation";
import { ChatPanel } from "./chat-panel.client";
import { LoginForm } from "./login-form.client";
import type { ChatState } from "./read.server";

export function Chat({ state }: { state: ChatState }) {
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">问答 / 邀请制</p>
          <h1>问一问这套预测系统。</h1>
          <p>回答只引用本站的赛程、赔率、阵容和成绩单，不是投注建议。所有时间均为北京时间。</p>
        </div>
        <span className="pill">按调用金额计额度</span>
      </div>
      {state.kind === "unconfigured" ? (
        <section className="panel">
          <EmptyState
            title="对话服务未接入"
            description="这个站点还没有配置问答服务，暂时不能提问。浏览比赛预测和成绩单不受影响。"
          />
        </section>
      ) : state.kind === "unavailable" ? (
        <section className="panel">
          <EmptyState title="对话服务暂时不可用" description={`${state.reason}，请稍后再试。`} />
        </section>
      ) : state.kind === "anonymous" ? (
        <section className="panel chat-login-panel">
          <h2>输入邀请码</h2>
          <p className="muted">邀请码由站点维护者发放。登录后 14 天内有效，可随时退出。</p>
          <LoginForm />
        </section>
      ) : (
        <ChatPanel user={state.user} csrf={state.csrf} quota={state.quota} />
      )}
    </>
  );
}
