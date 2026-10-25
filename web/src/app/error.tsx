"use client";

export default function ErrorPage() {
  return (
    <div className="empty-state" role="alert">
      <h1>数据暂时无法读取</h1>
      <p>当前没有可展示的有效结果，请稍后重试。这不表示比赛不存在。</p>
      {/* 新文档请求重新读取服务端数据；reset 单独调用会重用失败的 RSC。 */}
      <button className="button button-primary mt-5" onClick={() => window.location.reload()}>
        重新读取
      </button>
    </div>
  );
}
