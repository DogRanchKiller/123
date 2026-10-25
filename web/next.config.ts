import type { NextConfig } from "next";

const config: NextConfig = {
  poweredByHeader: false,
  // metadata 与比赛数据检查完成后再发送 HTML，避免流式响应提前锁定 200。
  htmlLimitedBots: /.*/,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Robots-Tag", value: "noindex, nofollow" },
          { key: "X-Content-Type-Options", value: "nosniff" },
        ],
      },
    ];
  },
};

export default config;
