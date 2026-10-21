/** client.ts 冒烟：URL 拼装（同源 /api/）、token 头、降级（网络挂/5xx/接线期 404）与业务错误（4xx）。 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  API_BASE,
  api,
  ApiError,
  ApiUnavailableError,
  asList,
  conflictText,
  setToken,
  stanceText,
  TOKEN_KEY,
  zhesiSource,
} from "./client";

// --- 测试环境 localStorage stub（node 无 DOM） ---
class LocalStorageStub {
  private m = new Map<string, string>();
  getItem(k: string) {
    return this.m.get(k) ?? null;
  }
  setItem(k: string, v: string) {
    this.m.set(k, v);
  }
  removeItem(k: string) {
    this.m.delete(k);
  }
}

const okJson = (body: unknown) => ({
  ok: true,
  status: 200,
  json: async () => body,
});
const failJson = (status: number, detail?: unknown) => ({
  ok: false,
  status,
  json: async () => (detail === undefined ? {} : { detail }),
});

beforeEach(() => {
  vi.stubGlobal("localStorage", new LocalStorageStub());
  setToken("ui-tok");
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("URL 拼装与 token 头", () => {
  it("GET 带 query：同源 /api/ 前缀 + ?project_id=，并带 Bearer token", async () => {
    const fetchMock = vi.fn(async () => okJson({ results: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await api.listScenes("p1");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [URL, RequestInit];
    expect(API_BASE).toBe(""); // 同源契约：默认无跨源 base
    expect(String(url)).toBe(`http://localhost/api/v1/screenplay/projects/p1/scenes`);
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer ui-tok");
    expect(init.method).toBe("GET");
    expect(init.body).toBeUndefined();
  });

  it("POST 带 JSON body 与 Content-Type（/api/screenplay/projects）", async () => {
    const fetchMock = vi.fn(async () => okJson({ id: "p1" }));
    vi.stubGlobal("fetch", fetchMock);

    await api.createProject({ title: "北渡", logline: "一个摆渡人的傍晚" });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [URL, RequestInit];
    expect(String(url)).toBe(`http://localhost/api/v1/screenplay/projects`);
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("content-type")).toBe("application/json");
    expect(JSON.parse(String(init.body))).toEqual({ title: "北渡", logline: "一个摆渡人的傍晚" });
  });

  it("PUT 分镜镜头：/api/pipeline/storyboard/{sb}/{idx}，idx 走编码", async () => {
    const fetchMock = vi.fn(async () => okJson({}));
    vi.stubGlobal("fetch", fetchMock);

    await api.updateShot("sb 1", 2, { idx: 2, shot_size: "特写", visual: "v", action: "a", line: "l", duration: 3 });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [URL, RequestInit];
    expect(String(url)).toBe(`http://localhost/api/v1/pipeline/storyboard/sb%201/2`);
    expect(init.method).toBe("PUT");
    expect(JSON.parse(String(init.body))).toMatchObject({ idx: 2, shot_size: "特写" });
  });

  it("DELETE 台词与路径参数 encodeURIComponent", async () => {
    const fetchMock = vi.fn(async () => okJson({}));
    vi.stubGlobal("fetch", fetchMock);

    await api.deleteLine("scene id/1", "line/9");
    await api.listCharacters("proj id/1");

    const [u1, init1] = fetchMock.mock.calls[0] as unknown as [URL, RequestInit];
    expect(String(u1)).toBe(`http://localhost/api/v1/screenplay/scenes/scene%20id%2F1/lines/line%2F9`);
    expect(init1.method).toBe("DELETE");
    const [u2] = fetchMock.mock.calls[1] as unknown as [URL, RequestInit];
    expect(String(u2)).toBe(`http://localhost/api/v1/screenplay/projects/proj%20id%2F1/characters`);
  });

  it("提示词 GET 带 form query", async () => {
    const fetchMock = vi.fn(async () => okJson({ prompts: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await api.getPrompt("ps1", "video");

    const [url] = fetchMock.mock.calls[0] as unknown as [URL, RequestInit];
    expect(String(url)).toBe(`http://localhost/api/v1/pipeline/prompts/ps1?form=video`);
  });

  it("未设 token 时不发 Authorization 头", async () => {
    setToken("");
    const fetchMock = vi.fn(async () => okJson({ results: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await api.listProjects();

    const [, init] = fetchMock.mock.calls[0] as unknown as [URL, RequestInit];
    expect(new Headers(init.headers).get("authorization")).toBeNull();
  });

  it("token 持久化在 localStorage['juchuang_token']", () => {
    const ls = new LocalStorageStub();
    vi.stubGlobal("localStorage", ls);
    setToken("t2");
    expect(ls.getItem(TOKEN_KEY)).toBe("t2");
    setToken("");
    expect(ls.getItem(TOKEN_KEY)).toBeNull();
  });
});

describe("降级与错误映射（后端并行开发期）", () => {
  it("fetch reject（网络/超时/拒绝连接）→ ApiUnavailableError", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("fetch failed"))));
    await expect(api.listProjects()).rejects.toBeInstanceOf(ApiUnavailableError);
    await expect(api.kernelStatus()).rejects.toBeInstanceOf(ApiUnavailableError);
    await expect(api.genStoryboard("s1")).rejects.toBeInstanceOf(ApiUnavailableError);
  });

  it("5xx → ApiUnavailableError", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => failJson(503, "boom")));
    await expect(api.kernelLink()).rejects.toBeInstanceOf(ApiUnavailableError);
    await expect(api.exportProject("p1")).rejects.toBeInstanceOf(ApiUnavailableError);
  });

  it("接线期端点 404 → ApiUnavailableError（默认 wired）", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => failJson(404, "Not Found")));
    await expect(api.listProjects()).rejects.toBeInstanceOf(ApiUnavailableError);
    await expect(api.kernelInject("p1", { scene_id: "s1" })).rejects.toBeInstanceOf(ApiUnavailableError);
    await expect(api.genPrompts("sb1")).rejects.toBeInstanceOf(ApiUnavailableError);
  });

  it("200 但 body 非 JSON（本地 preview 把 /api/ 落到 SPA 回退页）→ ApiUnavailableError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, status: 200, json: async () => Promise.reject(new SyntaxError("Unexpected token <")) })),
    );
    await expect(api.listProjects()).rejects.toBeInstanceOf(ApiUnavailableError);
  });

  it("4xx 带 detail → ApiError(status, detail)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => failJson(401, "missing bearer token")));
    const err = await api.listProjects().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    const apiErr = err as ApiError;
    expect(apiErr.status).toBe(401);
    expect(apiErr.message).toContain("missing bearer token");
  });
});

describe("契约辅助函数", () => {
  it("asList：{results:[...]} / [...] / 空值", () => {
    expect(asList({ results: [1, 2] })).toEqual([1, 2]);
    expect(asList([3])).toEqual([3]);
    expect(asList(null)).toEqual([]);
    expect(asList({ unexpected: true })).toEqual([]);
  });

  it("zhesiSource：识别注入元数据（source 标记或卡 ID）", () => {
    expect(zhesiSource({ description: "自由 ↔ 决定", source: "zhesi", card_ids: ["z1", "z2"] })).toEqual({
      source: "zhesi",
      cardIds: ["z1", "z2"],
    });
    expect(zhesiSource({ text: "保守派", card_ids: ["z9"] })).toEqual({ source: "zhesi", cardIds: ["z9"] });
    expect(zhesiSource("只是一个普通立场")).toBeNull();
    expect(zhesiSource({ text: "自建立场" })).toBeNull();
    expect(zhesiSource(null)).toBeNull();
  });

  it("stanceText / conflictText：string 直出，对象防御式拼", () => {
    expect(stanceText("自由万岁")).toBe("自由万岁");
    expect(stanceText({ text: "决定论者", source: "zhesi" })).toBe("决定论者");
    expect(stanceText(null)).toBe("");
    expect(conflictText("渡与不渡")).toBe("渡与不渡");
    expect(conflictText({ a: "自由", b: "决定", source: "zhesi" })).toBe("自由 ↔ 决定");
    expect(conflictText({ description: "留下的理由" })).toBe("留下的理由");
  });
});
