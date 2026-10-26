import "server-only";
import { connection } from "next/server";

/** 只读接口（python -m server）的服务端读取。只在服务端组件里调用，浏览器不直接访问接口。 */

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** 是否配置了 API_URL（不校验地址）；只决定页面标签，地址错误由读取时报出。 */
export async function apiConfigured(): Promise<boolean> {
  await connection();
  return Boolean(process.env.API_URL?.trim());
}

/** 运行时读取 API_URL（不在构建时固定）；未配置时返回 null，页面使用演示样本。 */
export async function apiBase(): Promise<string | null> {
  await connection();
  const raw = process.env.API_URL?.trim();
  if (!raw) return null;
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new ApiError("API_URL 不是有效地址：" + raw, null);
  }
  if (url.protocol !== "http:" && url.protocol !== "https:")
    throw new ApiError("API_URL 只能是 http 或 https 地址", null);
  return url.href.replace(/\/$/, "");
}

/** GET 一个 JSON；404 返回 null，其余非 2xx（含 503 无快照）和网络错误都抛 ApiError。 */
export async function getJson<T>(base: string, path: string): Promise<T | null> {
  let response: Response;
  try {
    response = await fetch(base + path, {
      cache: "no-store",
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(10_000),
    });
  } catch (error) {
    throw new ApiError("只读接口连接失败：" + String(error), null);
  }
  if (response.status === 404) return null;
  if (!response.ok)
    throw new ApiError("只读接口返回 " + response.status, response.status);
  return (await response.json()) as T;
}
