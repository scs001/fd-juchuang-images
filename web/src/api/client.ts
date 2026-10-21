/**
 * 极简 API client（原生 fetch，不引第三方库）。
 *
 * - 契约：同源 /api/ 前缀（部署态 nginx 反代 fd-juchuang-api）。
 *   本地联调可设 VITE_JUCHUANG_API_BASE 指到后端（如 http://127.0.0.1:8010）。
 * - token 存 localStorage["juchuang_token"]（顶栏输入框 / Logto 登录写入）。
 * - 后端与界面并行开发：所有端点视为 wired——网络错误、超时、5xx、404/501
 *   统一抛 ApiUnavailableError，界面据此渲染「该能力接线中」降级态，不白屏。
 */

export const API_BASE: string = (() => {
  const raw = import.meta.env?.VITE_JUCHUANG_API_BASE;
  return typeof raw === "string" && raw.trim() ? raw.trim().replace(/\/+$/, "") : "";
})();

export const TOKEN_KEY = "juchuang_token";
const TIMEOUT_MS = 30_000;

// ---- token 存取（非浏览器环境退化为内存 shim，测试可用） ----

const memoryStore = new Map<string, string>();
const shim: Pick<Storage, "getItem" | "setItem" | "removeItem"> = {
  getItem: (k) => memoryStore.get(k) ?? null,
  setItem: (k, v) => void memoryStore.set(k, v),
  removeItem: (k) => void memoryStore.delete(k),
};
function store(): Pick<Storage, "getItem" | "setItem" | "removeItem"> {
  try {
    if (typeof localStorage !== "undefined") return localStorage;
  } catch {
    /* 隐私模式等场景落到内存 shim */
  }
  return shim;
}
export function getToken(): string {
  return store().getItem(TOKEN_KEY) ?? "";
}
export function setToken(token: string): void {
  if (token) store().setItem(TOKEN_KEY, token);
  else store().removeItem(TOKEN_KEY);
}

// ---- 错误类型 ----

/** 「该能力接线中」：网络失败/超时/5xx，或并行接线期端点 404/501。 */
export class ApiUnavailableError extends Error {
  constructor(message = "capability not wired yet") {
    super(message);
    this.name = "ApiUnavailableError";
  }
}

/** 业务错误（4xx 等），message 携带后端 detail。 */
export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// ---- 请求 ----

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  query?: Record<string, string>;
  /** 接线期端点：404/501 也视为「未接线」而非业务错误（默认开） */
  wired?: boolean;
}

/** 同源相对路径在浏览器取当前 origin；非浏览器（测试）落到 http://localhost。 */
function toUrl(path: string, query?: Record<string, string>): URL {
  const qs = new URLSearchParams(query ?? {});
  const full = `${API_BASE}${path}${[...qs.keys()].length ? `?${qs.toString()}` : ""}`;
  if (/^https?:\/\//i.test(full)) return new URL(full);
  const origin =
    typeof location !== "undefined" && /^https?:/i.test(String(location.origin))
      ? String(location.origin)
      : "http://localhost";
  return new URL(full, origin);
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const url = toUrl(path, opts.query);

  const token = getToken();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const hasBody = opts.body !== undefined;
  if (hasBody) headers["Content-Type"] = "application/json";

  let resp: Response;
  try {
    resp = await fetch(url, {
      method: opts.method ?? (hasBody ? "POST" : "GET"),
      headers,
      body: hasBody ? JSON.stringify(opts.body) : undefined,
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch {
    // 网络拒绝 / DNS / CORS / 超时（AbortError/TimeoutError）→ 接线中降级
    throw new ApiUnavailableError();
  }

  const wired = opts.wired !== false;
  if (!resp.ok) {
    const unwired = resp.status >= 500 || resp.status === 501 || (wired && resp.status === 404);
    if (unwired) throw new ApiUnavailableError();
    let detail: unknown = "";
    try {
      detail = (await resp.json())?.detail ?? "";
    } catch {
      /* 无 JSON body */
    }
    const message = typeof detail === "string" && detail ? detail : `HTTP ${resp.status}`;
    throw new ApiError(resp.status, message);
  }
  if (resp.status === 204) return undefined as T;
  try {
    return (await resp.json()) as T;
  } catch {
    // 200 但 body 不是 JSON（如本地 preview 把 /api/ 落到 SPA 回退页）→ 视为未接线
    if (wired) throw new ApiUnavailableError();
    throw new ApiError(resp.status, "invalid JSON response");
  }
}

const enc = encodeURIComponent;

// ---- 契约类型（后端并行开发，字段防御式可选） ----

export interface Project {
  id: string;
  title?: string | null;
  logline?: string | null;
  created_at?: string;
  updated_at?: string;
}

/** 立场/冲突可能是纯文本，也可能是哲思注入的结构化元数据（D2：注入落元数据）。 */
export interface StanceMeta {
  text?: string;
  position?: string;
  reason?: string | null;
  source?: string;
  origin?: string;
  card_ids?: string[];
  source_cards?: string[];
}

export interface Character {
  id: string;
  name: string;
  appearance?: Record<string, string> | null;
  stance?: string | StanceMeta | null;
  created_at?: string;
}

export interface ConflictMeta {
  description?: string;
  a?: string;
  b?: string;
  source?: string;
  origin?: string;
  card_ids?: string[];
  source_cards?: string[];
  tension_pair?: unknown;
}

export interface Scene {
  id: string;
  project_id?: string;
  title?: string | null;
  conflict?: string | ConflictMeta | null;
  order?: number;
  created_at?: string;
}

export interface Line {
  id: string;
  character_id?: string | null;
  character_name?: string | null;
  text?: string | null;
  order?: number;
}

export interface VersionEntry {
  id: string;
  label?: string | null;
  created_at?: string;
  version?: number;
}

export interface StoryboardShot {
  idx: number;
  shot_size?: string | null;
  visual?: string | null;
  action?: string | null;
  line?: string | null;
  duration?: number | string | null;
}

export interface Storyboard {
  id: string;
  scene_id?: string;
  shots?: StoryboardShot[];
}

export type PromptForm = "image" | "video" | "narrative";
export const PROMPT_FORMS: readonly PromptForm[] = ["image", "video", "narrative"];

export interface KernelCard {
  id: string;
  question?: string | null;
  position?: string | null;
  title?: string | null;
}

export interface KernelStatus {
  mode: string; // "linked" | "standalone"（防御式 string）
  card_count?: number;
  reason?: string | null;
  cards?: KernelCard[] | null;
  linked_at?: string | null;
}

/** 提示词集合引用：POST /pipeline/prompts/{sb} 的返回（至少带 id）。 */
export interface PromptSetRef {
  id: string;
  [k: string]: unknown;
}

// ---- 哲思来源标记（注入后 conflict/stance 显示 zhesi 来源） ----

export interface ZhesiSource {
  source: string;
  cardIds: string[];
}

/** 从 conflict/stance 值里识别哲思来源：对象带 zhesi/哲思 source 或卡 ID 列表即视为已注入。 */
export function zhesiSource(value: unknown): ZhesiSource | null {
  if (!value || typeof value !== "object") return null;
  const o = value as Record<string, unknown>;
  const src = `${String(o.source ?? "")} ${String(o.origin ?? "")}`;
  const ids = [o.card_ids, o.source_cards, (o.tension_pair as Record<string, unknown> | undefined)?.card_ids]
    .filter(Array.isArray)
    .flat()
    .filter((v): v is string => typeof v === "string" && v.length > 0);
  const marked = /zhesi|哲思/i.test(src) || ids.length > 0;
  if (!marked) return null;
  return { source: /zhesi|哲思/i.test(src) ? src.trim().split(/\s+/)[0] : "zhesi", cardIds: ids };
}

/** 立场文本：string 直出；对象按 text/position/reason 拼 Defensive。 */
export function stanceText(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "object") {
    const o = value as Record<string, unknown>;
    const text = [o.text, o.position, o.reason].find((v) => typeof v === "string" && v);
    return typeof text === "string" ? text : "";
  }
  return String(value);
}

/** 冲突文本：string 直出；对象按 description / a↔b 拼。 */
export function conflictText(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "object") {
    const o = value as Record<string, unknown>;
    if (typeof o.description === "string" && o.description) return o.description;
    const a = typeof o.a === "string" ? o.a : "";
    const b = typeof o.b === "string" ? o.b : "";
    if (a || b) return [a, b].filter(Boolean).join(" ↔ ");
    return "";
  }
  return String(value);
}

/** 列表响应防御式取数：{results:[...]} / [...] / 空值。 */
export function asList<T>(payload: unknown): T[] {
  if (Array.isArray(payload)) return payload as T[];
  if (payload && typeof payload === "object") {
    const r = (payload as Record<string, unknown>).results;
    if (Array.isArray(r)) return r as T[];
  }
  return [];
}

/** JSON 下载（Blob），导出底料用。 */
export function downloadJson(filename: string, data: unknown): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ---- API 面（对齐 ../server 契约，全部 wired：接线期 404/5xx → 接线中） ----

export const api = {
  // 剧本：项目 / 角色卡 / 场次 / 台词 / 版本 / 导出
  listProjects: () =>
    request<unknown>("/api/v1/screenplay/projects").then((r) => asList<Project>(r)),
  createProject: (b: { title: string; logline?: string }) =>
    request<Project>("/api/v1/screenplay/projects", { method: "POST", body: b }),

  listCharacters: (projectId: string) =>
    request<unknown>(`/api/v1/screenplay/projects/${enc(projectId)}/characters`).then((r) =>
      asList<Character>(r),
    ),
  createCharacter: (
    projectId: string,
    b: { name: string; appearance: Record<string, string>; stance?: string },
  ) =>
    request<Character>(`/api/v1/screenplay/projects/${enc(projectId)}/characters`, {
      method: "POST",
      body: b,
    }),
  updateCharacter: (
    projectId: string,
    characterId: string,
    b: { name: string; appearance: Record<string, string>; stance?: string },
  ) =>
    request<Character>(`/api/v1/screenplay/projects/${enc(projectId)}/characters/${enc(characterId)}`, {
      method: "PUT",
      body: b,
    }),
  deleteCharacter: (projectId: string, characterId: string) =>
    request<unknown>(`/api/v1/screenplay/projects/${enc(projectId)}/characters/${enc(characterId)}`, {
      method: "DELETE",
    }),

  listScenes: (projectId: string) =>
    request<unknown>(`/api/v1/screenplay/projects/${enc(projectId)}/scenes`).then((r) =>
      asList<Scene>(r),
    ),
  createScene: (projectId: string, b: { title: string; conflict?: string }) =>
    request<Scene>(`/api/v1/screenplay/projects/${enc(projectId)}/scenes`, {
      method: "POST",
      body: b,
    }),
  updateScene: (projectId: string, sceneId: string, b: { title?: string; conflict?: string }) =>
    request<Scene>(`/api/v1/screenplay/projects/${enc(projectId)}/scenes/${enc(sceneId)}`, {
      method: "PUT",
      body: b,
    }),
  deleteScene: (projectId: string, sceneId: string) =>
    request<unknown>(`/api/v1/screenplay/projects/${enc(projectId)}/scenes/${enc(sceneId)}`, {
      method: "DELETE",
    }),

  listLines: (sceneId: string) =>
    request<unknown>(`/api/v1/screenplay/scenes/${enc(sceneId)}/lines`).then((r) => asList<Line>(r)),
  createLine: (sceneId: string, b: { character_id?: string; text: string }) =>
    request<Line>(`/api/v1/screenplay/scenes/${enc(sceneId)}/lines`, { method: "POST", body: b }),
  updateLine: (sceneId: string, lineId: string, b: { character_id?: string; text: string }) =>
    request<Line>(`/api/v1/screenplay/scenes/${enc(sceneId)}/lines/${enc(lineId)}`, { method: "PUT", body: b }),
  deleteLine: (sceneId: string, lineId: string) =>
    request<unknown>(`/api/v1/screenplay/scenes/${enc(sceneId)}/lines/${enc(lineId)}`, { method: "DELETE" }),

  listVersions: (projectId: string) =>
    request<unknown>(`/api/v1/screenplay/projects/${enc(projectId)}/versions`).then((r) =>
      asList<VersionEntry>(r),
    ),
  createVersion: (projectId: string, label?: string) =>
    request<VersionEntry>(`/api/v1/screenplay/projects/${enc(projectId)}/versions`, {
      method: "POST",
      body: label ? { label } : {},
    }),
  restoreVersion: (projectId: string, versionId: string) =>
    request<unknown>(`/api/v1/screenplay/projects/${enc(projectId)}/restore/${enc(versionId)}`, {
      method: "POST",
      body: {},
    }),
  exportProject: (projectId: string) =>
    request<unknown>(`/api/v1/screenplay/projects/${enc(projectId)}/export`),

  // 哲思内核：接入 / 状态 / 注入
  kernelLink: () => request<KernelStatus>("/api/v1/kernel/link", { method: "POST", body: {} }),
  kernelStatus: () => request<KernelStatus>("/api/v1/kernel/status"),
  kernelInject: (projectId: string, b: { scene_id?: string; character_id?: string }) =>
    request<unknown>(`/api/v1/kernel/inject/${enc(projectId)}`, { method: "POST", body: b }),

  // 底料：分镜表 / 镜头编辑 / 三形态提示词
  genStoryboard: (sceneId: string) =>
    request<Storyboard>(`/api/v1/pipeline/storyboard/${enc(sceneId)}`, { method: "POST", body: {} }),
  updateShot: (storyboardId: string, idx: number, shot: StoryboardShot) =>
    request<unknown>(`/api/v1/pipeline/storyboard/${enc(storyboardId)}/${enc(String(idx))}`, {
      method: "PUT",
      body: shot,
    }),
  genPrompts: (storyboardId: string) =>
    request<PromptSetRef>(`/api/v1/pipeline/prompts/${enc(storyboardId)}`, { method: "POST", body: {} }),
  getPrompt: (promptSetId: string, form: PromptForm) =>
    request<unknown>(`/api/v1/pipeline/prompts/${enc(promptSetId)}`, { query: { form } }),
};
