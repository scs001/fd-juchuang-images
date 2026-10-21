/**
 * 面向 UI 的加载态与错误映射。
 * fetch 挂掉/超时/5xx/接线期 404 → unavailable（「该能力接线中」）；4xx → error（业务报错）。
 */
import { ApiError, ApiUnavailableError } from "./client";

export type Loadable<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "unavailable" }
  | { status: "error"; message: string; code?: number };

export type Errored = Extract<Loadable<unknown>, { status: "error" }>;

/** 操作反馈：成功文案 / 业务报错 / 接线中降级。 */
export type Note = { ok: string } | { err: string } | { unavailable: true } | null;

export function mapApiError(e: unknown): Errored | { status: "unavailable" } {
  if (e instanceof ApiUnavailableError) return { status: "unavailable" };
  if (e instanceof ApiError) return { status: "error", message: e.message, code: e.status };
  return { status: "error", message: e instanceof Error ? e.message : String(e) };
}

/** 把 catch 到的异常折成 Note：unavailable → 降级；error → 文案。 */
export function noteFromError(e: unknown): Note {
  const mapped = mapApiError(e);
  if (mapped.status === "unavailable") return { unavailable: true };
  return { err: mapped.message };
}
