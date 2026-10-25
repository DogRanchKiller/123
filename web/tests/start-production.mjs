import { writeFileSync } from "node:fs";
import { spawn } from "node:child_process";
import { resolve } from "node:path";

// 故障只由本机测试配置注入，网站没有测试控制路由。
writeFileSync(resolve(".test-control.json"), JSON.stringify({ failIds: [] }));
const child = spawn(
  process.execPath,
  [
    "node_modules/next/dist/bin/next",
    "start",
    "--hostname",
    "127.0.0.1",
    "--port",
    "3100",
  ],
  { stdio: "inherit", env: process.env },
);
for (const signal of ["SIGINT", "SIGTERM"])
  process.on(signal, () => child.kill(signal));
child.on("exit", (code) => process.exit(code ?? 0));
