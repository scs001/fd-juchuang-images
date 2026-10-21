/**
 * Workbench 冒烟：API 全挂（mock fetch reject）时三个 tab 的降级渲染，以及就绪态关键交互。
 * 无 jsdom 依赖，用 react-dom/server renderToString 直渲视图层
 * （视图与容器同文件，容器 useEffect 走的就是同一 mapApiError 映射，
 *  client.test.ts 已覆盖 fetch reject → ApiUnavailableError）。
 */
import { renderToString } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import "../../i18n";
import { api, ApiUnavailableError, type Project, type Character, type Scene, type Line, type VersionEntry, type Storyboard, type KernelStatus } from "../../api/client";
import { mapApiError } from "../../api/state";
import { ScreenplayView } from "./ScreenplayPanel";
import { KernelView } from "./KernelPanel";
import { PipelineView } from "./PipelinePanel";

const noop = () => {};

describe("API 全挂时的降级态", () => {
  it("mock fetch reject：面板实际调用的加载路径映射为 unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("fetch failed"))));
    // 这些正是三个容器 useEffect 里跑的调用
    await expect(api.listProjects()).rejects.toBeInstanceOf(ApiUnavailableError);
    await expect(api.kernelStatus()).rejects.toBeInstanceOf(ApiUnavailableError);
    await expect(api.listScenes("p1")).rejects.toBeInstanceOf(ApiUnavailableError);
    await expect(api.genStoryboard("s1")).rejects.toBeInstanceOf(ApiUnavailableError);
    await expect(api.listVersions("p1")).rejects.toBeInstanceOf(ApiUnavailableError);
    // 容器 catch 后套用的映射
    expect(mapApiError(new ApiUnavailableError())).toEqual({ status: "unavailable" });
    vi.unstubAllGlobals();
  });

  it("剧本：项目/角色/场次/版本 unavailable → 渲染「接线中」而非白屏，入口仍在", () => {
    const html = renderToString(
      <ScreenplayView
        projects={{ status: "unavailable" }}
        onCreateProject={noop}
        createBusy={false}
        createNote={null}
        selectedProjectId=""
        onSelectProject={noop}
        selectedProject={null}
        characters={{ status: "unavailable" }}
        onSaveCharacter={noop}
        onDeleteCharacter={noop}
        charBusy={false}
        charNote={null}
        scenes={{ status: "unavailable" }}
        onCreateScene={noop}
        sceneCreateBusy={false}
        sceneCreateNote={null}
        selectedSceneId=""
        onSelectScene={noop}
        onSaveScene={noop}
        sceneBusy={false}
        sceneNote={null}
        lines={{ status: "unavailable" }}
        onAddLine={noop}
        onUpdateLine={noop}
        onDeleteLine={noop}
        lineBusy={false}
        versions={{ status: "unavailable" }}
        onSnapshot={noop}
        onRestore={noop}
        restoreBusyId={null}
        versionBusy={false}
        restoreNote={null}
        onExport={noop}
        exportBusy={false}
        exportNote={null}
      />,
    );
    expect(html).toContain("接线中");
    // 新建入口仍在，白屏恢复无死角
    expect(html).toContain("新建项目");
  });

  it("哲思：状态 unavailable → 渲染「接线中」，接入按钮仍在", () => {
    const html = renderToString(
      <KernelView
        status={{ status: "unavailable" }}
        onLink={noop}
        linkBusy={false}
        linkNote={null}
        projects={{ status: "unavailable" }}
        selectedProjectId=""
        onSelectProject={noop}
        scenes={{ status: "unavailable" }}
        selectedSceneId=""
        onSelectScene={noop}
        characters={{ status: "unavailable" }}
        selectedCharacterId=""
        onSelectCharacter={noop}
        onInject={noop}
        injectBusy={false}
        injectNote={null}
      />,
    );
    expect(html).toContain("接线中");
    expect(html).toContain("接入哲思");
  });

  it("底料：项目/分镜 unavailable → 渲染「接线中」，生成入口仍在", () => {
    const html = renderToString(
      <PipelineView
        projects={{ status: "unavailable" }}
        selectedProjectId=""
        onSelectProject={noop}
        scenes={{ status: "unavailable" }}
        selectedSceneId=""
        onSelectScene={noop}
        storyboard={{ status: "unavailable" }}
        onGenerateStoryboard={noop}
        sbBusy={false}
        sbNote={null}
        onUpdateShot={noop}
        shotBusyIdx={null}
        prompts={null}
        onGenPrompts={noop}
        promptBusy={false}
        promptNote={null}
        form="image"
        onForm={noop}
        promptData={{ status: "idle" }}
        onDownload={noop}
        downloadBusy={false}
        downloadNote={null}
      />,
    );
    expect(html).toContain("接线中");
    expect(html).toContain("生成分镜表");
  });
});

describe("就绪态关键渲染", () => {
  const project: Project = { id: "p1", title: "北渡", logline: "摆渡人的傍晚" };
  const characters: Character[] = [
    {
      id: "c1",
      name: "林远",
      appearance: { 年龄感: "中年", 着装: "旧呢大衣" },
      stance: { text: "人可以不渡河", source: "zhesi", card_ids: ["z1"] },
    },
    { id: "c2", name: "少年", appearance: { 年龄感: "少年", 着装: "校服" } },
  ];
  const scenes: Scene[] = [
    {
      id: "s1",
      project_id: "p1",
      title: "码头对手戏",
      conflict: { a: "渡", b: "不渡", source: "zhesi", card_ids: ["z1", "z2"] },
    },
  ];
  const lines: Line[] = [
    { id: "l1", character_id: "c1", character_name: "林远", text: "今晚不起雾。" },
  ];
  const versions: VersionEntry[] = [
    { id: "v2", label: "加了台词", created_at: "2026-10-02T10:00:00" },
    { id: "v1", label: "初稿", created_at: "2026-10-01T09:00:00" },
  ];

  const screenplayReady = {
    projects: { status: "ready" as const, data: [project] },
    onCreateProject: noop,
    createBusy: false,
    createNote: null,
    selectedProjectId: "p1",
    onSelectProject: noop,
    selectedProject: project,
    characters: { status: "ready" as const, data: characters },
    onSaveCharacter: noop,
    onDeleteCharacter: noop,
    charBusy: false,
    charNote: null,
    scenes: { status: "ready" as const, data: scenes },
    onCreateScene: noop,
    sceneCreateBusy: false,
    sceneCreateNote: null,
    selectedSceneId: "s1",
    onSelectScene: noop,
    onSaveScene: noop,
    sceneBusy: false,
    sceneNote: null,
    lines: { status: "ready" as const, data: lines },
    onAddLine: noop,
    onUpdateLine: noop,
    onDeleteLine: noop,
    lineBusy: false,
    versions: { status: "ready" as const, data: versions },
    onSnapshot: noop,
    onRestore: noop,
    restoreBusyId: null,
    versionBusy: false,
    restoreNote: null,
    onExport: noop,
    exportBusy: false,
    exportNote: null,
  };

  it("剧本：项目/角色/场次/台词/版本就绪；注入过的立场与冲突带「哲思」来源标记", () => {
    const html = renderToString(<ScreenplayView {...screenplayReady} />);
    expect(html).toContain("北渡");
    expect(html).toContain("林远");
    expect(html).toContain("人可以不渡河"); // stance 文本（对象防御式）
    expect(html).toContain("码头对手戏");
    expect(html).toContain("渡 ↔ 不渡"); // conflict 文本（对象防御式）
    expect(html).toContain("今晚不起雾。");
    expect(html).toContain("初稿"); // 版本时间线
    expect(html).toContain("回滚到此版本");
    expect(html).toContain("导出 JSON");
    // 哲思来源标记（badge）
    expect(html.match(/哲思/g)?.length ?? 0).toBeGreaterThanOrEqual(2);
  });

  it("哲思：linked 状态绿徽标 + 缓存卡列表 + 注入按钮", () => {
    const status: KernelStatus = {
      mode: "linked",
      card_count: 2,
      cards: [
        { id: "z1", question: "自由还是决定", position: "自由" },
        { id: "z2", question: "本质还是建构", position: "建构" },
      ],
    };
    const html = renderToString(
      <KernelView
        status={{ status: "ready", data: status }}
        onLink={noop}
        linkBusy={false}
        linkNote={null}
        projects={{ status: "ready", data: [project] }}
        selectedProjectId="p1"
        onSelectProject={noop}
        scenes={{ status: "ready", data: scenes }}
        selectedSceneId="s1"
        onSelectScene={noop}
        characters={{ status: "ready", data: characters }}
        selectedCharacterId=""
        onSelectCharacter={noop}
        onInject={noop}
        injectBusy={false}
        injectNote={null}
      />,
    );
    expect(html).toContain("已接入");
    expect(html).toContain("缓存卡 2 张");
    expect(html).toContain("自由还是决定");
    expect(html).toContain("注入");
  });

  it("哲思：standalone 灰徽标 + 原因", () => {
    const html = renderToString(
      <KernelView
        status={{ status: "ready", data: { mode: "standalone", card_count: 0, reason: "契约不可达" } }}
        onLink={noop}
        linkBusy={false}
        linkNote={null}
        projects={{ status: "ready", data: [] }}
        selectedProjectId=""
        onSelectProject={noop}
        scenes={{ status: "idle" }}
        selectedSceneId=""
        onSelectScene={noop}
        characters={{ status: "idle" }}
        selectedCharacterId=""
        onSelectCharacter={noop}
        onInject={noop}
        injectBusy={false}
        injectNote={null}
      />,
    );
    expect(html).toContain("独立模式");
    expect(html).toContain("契约不可达");
  });

  it("底料：分镜表就绪渲染可编辑表格与时长；提示词就绪渲染 JSON 预览与下载", () => {
    const storyboard: Storyboard = {
      id: "sb1",
      scene_id: "s1",
      shots: [
        { idx: 0, shot_size: "特写", visual: "雨夜窗前", action: "抬头", line: "你回来了", duration: 3 },
        { idx: 1, shot_size: "全景", visual: "空码头", action: "沉默", line: "（无）", duration: 5 },
      ],
    };
    const html = renderToString(
      <PipelineView
        projects={{ status: "ready", data: [project] }}
        selectedProjectId="p1"
        onSelectProject={noop}
        scenes={{ status: "ready", data: scenes }}
        selectedSceneId="s1"
        onSelectScene={noop}
        storyboard={{ status: "ready", data: storyboard }}
        onGenerateStoryboard={noop}
        sbBusy={false}
        sbNote={null}
        onUpdateShot={noop}
        shotBusyIdx={null}
        prompts={{ id: "ps1" }}
        onGenPrompts={noop}
        promptBusy={false}
        promptNote={null}
        form="image"
        onForm={noop}
        promptData={{ status: "ready", data: { subject: "雨夜窗前的中年男人", style: "胶片" } }}
        onDownload={noop}
        downloadBusy={false}
        downloadNote={null}
      />,
    );
    // 表头与镜头行
    expect(html).toContain("景别");
    expect(html).toContain("画面");
    expect(html).toContain("时长(秒)");
    expect(html).toContain("特写");
    expect(html).toContain("雨夜窗前的中年男人"); // 提示词 JSON 预览
    expect(html).toContain("下载 JSON");
    expect(html).toContain("视频"); // 三形态 tab
    expect(html).toContain("文本");
  });
});
