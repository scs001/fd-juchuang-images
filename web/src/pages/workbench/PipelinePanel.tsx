/** 底料 · AI 生成管线：选场次 → 生成分镜表（可编辑镜头表）→ 三形态提示词预览 + JSON 下载。 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  api,
  downloadJson,
  PROMPT_FORMS,
  type Project,
  type PromptForm,
  type Scene,
  type Storyboard,
  type StoryboardShot,
} from "../../api/client";
import { Loadable, mapApiError, noteFromError, type Note } from "../../api/state";
import {
  btnPrimary,
  btnSecondary,
  DegradeBox,
  EmptyLine,
  ErrorBox,
  inputText,
  LoadBox,
  Loading,
  NoteBox,
  Picker,
  SectionTitle,
} from "../../components/ui";

/** 防御式镜头行：兼容常见键名（shot_size/scale/景别 等），统一为规范字段。 */
export function normalizeShot(raw: unknown, i: number): StoryboardShot {
  if (!raw || typeof raw !== "object") return { idx: i, shot_size: "", visual: "", action: "", line: "", duration: "" };
  const o = raw as Record<string, unknown>;
  const pick = (...keys: string[]): string => {
    for (const k of keys) {
      const v = o[k];
      if (typeof v === "string" && v) return v;
      if (typeof v === "number") return String(v);
    }
    return "";
  };
  const dur = o.duration ?? o.seconds ?? o.length;
  return {
    idx: typeof o.idx === "number" ? o.idx : i,
    shot_size: pick("shot_size", "shot", "scale", "景别"),
    visual: pick("visual", "frame", "image", "picture", "画面"),
    action: pick("action", "动作"),
    line: pick("line", "dialogue", "text", "台词"),
    duration: typeof dur === "number" || typeof dur === "string" ? dur : "",
  };
}

function normalizeStoryboard(sb: Storyboard): Storyboard {
  const shots = (sb.shots ?? []).map(normalizeShot);
  return { ...sb, id: String(sb.id ?? ""), shots };
}

// ---- 视图（显式状态，可独立渲染降级态） ----

export function PipelineView({
  projects,
  selectedProjectId,
  onSelectProject,
  scenes,
  selectedSceneId,
  onSelectScene,
  storyboard,
  onGenerateStoryboard,
  sbBusy,
  sbNote,
  onUpdateShot,
  shotBusyIdx,
  prompts,
  onGenPrompts,
  promptBusy,
  promptNote,
  form,
  onForm,
  promptData,
  onDownload,
  downloadBusy,
  downloadNote,
}: {
  projects: Loadable<Project[]>;
  selectedProjectId: string;
  onSelectProject: (id: string) => void;
  scenes: Loadable<Scene[]>;
  selectedSceneId: string;
  onSelectScene: (id: string) => void;
  storyboard: Loadable<Storyboard>;
  onGenerateStoryboard: () => void;
  sbBusy: boolean;
  sbNote: Note;
  onUpdateShot: (shot: StoryboardShot) => void;
  shotBusyIdx: number | null;
  prompts: { id: string } | null;
  onGenPrompts: () => void;
  promptBusy: boolean;
  promptNote: Note;
  form: PromptForm;
  onForm: (f: PromptForm) => void;
  promptData: Loadable<unknown>;
  onDownload: () => void;
  downloadBusy: boolean;
  downloadNote: Note;
}) {
  const { t } = useTranslation();
  return (
    <section className="space-y-8">
      <div>
        <SectionTitle>{t("workbench.pipeline.heading")}</SectionTitle>
        <p className="mt-1 text-sm text-neutral-500">{t("workbench.pipeline.hint")}</p>
      </div>

      {/* 第一步：选场次 → 生成分镜 */}
      <div className="rounded-lg border border-neutral-200 bg-white p-5">
        <SectionTitle>{t("workbench.pipeline.step1")}</SectionTitle>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <Picker
            label={t("workbench.pipeline.project")}
            state={projects}
            selectedId={selectedProjectId}
            onSelect={onSelectProject}
            labelOf={(p: Project) => p.title || p.id}
          />
          <Picker
            label={t("workbench.pipeline.scene")}
            state={scenes}
            selectedId={selectedSceneId}
            onSelect={onSelectScene}
            labelOf={(s: Scene) => s.title || s.id.slice(0, 8)}
          />
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={sbBusy || !selectedSceneId}
            onClick={onGenerateStoryboard}
            className={btnPrimary}
          >
            {sbBusy ? t("workbench.pipeline.generating") : t("workbench.pipeline.genStoryboard")}
          </button>
          {!selectedSceneId ? (
            <span className="text-xs text-neutral-400">{t("workbench.pipeline.pickScene")}</span>
          ) : null}
        </div>
        <div className="mt-2">
          <NoteBox note={sbNote} />
        </div>

        {/* 镜头表（可编辑） */}
        <div className="mt-5">
          <LoadBox state={storyboard}>
            {(sb) =>
              (sb.shots ?? []).length === 0 ? (
                <EmptyLine>{t("workbench.pipeline.storyboardEmpty")}</EmptyLine>
              ) : (
                <div className="overflow-x-auto" data-testid="storyboard-table">
                  <table className="w-full min-w-3xl border-collapse text-sm">
                    <thead>
                      <tr className="border-b border-neutral-200 text-left text-xs text-neutral-400">
                        <th className="py-2 pr-2 font-normal">#</th>
                        <th className="py-2 pr-2 font-normal">{t("workbench.pipeline.shot")}</th>
                        <th className="py-2 pr-2 font-normal">{t("workbench.pipeline.visual")}</th>
                        <th className="py-2 pr-2 font-normal">{t("workbench.pipeline.action")}</th>
                        <th className="py-2 pr-2 font-normal">{t("workbench.pipeline.line")}</th>
                        <th className="py-2 pr-2 font-normal">{t("workbench.pipeline.duration")}</th>
                        <th className="py-2 font-normal" />
                      </tr>
                    </thead>
                    <tbody>
                      {(sb.shots ?? []).map((shot) => (
                        <ShotRow
                          key={`${shot.idx}-${sb.id}`}
                          shot={shot}
                          busy={shotBusyIdx === shot.idx}
                          onSave={onUpdateShot}
                        />
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            }
          </LoadBox>
        </div>
      </div>

      {/* 第二步：分镜 → 三形态提示词 */}
      <div className="rounded-lg border border-neutral-200 bg-white p-5">
        <SectionTitle>{t("workbench.pipeline.step2")}</SectionTitle>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={promptBusy || storyboard.status !== "ready"}
            onClick={onGenPrompts}
            className={btnPrimary}
          >
            {promptBusy ? t("workbench.pipeline.genPromptsBusy") : t("workbench.pipeline.genPrompts")}
          </button>
          {prompts ? (
            <button type="button" disabled={downloadBusy} onClick={onDownload} className={btnSecondary}>
              {downloadBusy ? t("workbench.pipeline.downloading") : t("workbench.pipeline.download")}
            </button>
          ) : null}
        </div>
        <div className="mt-2 space-y-2">
          <NoteBox note={promptNote} />
          <NoteBox note={downloadNote} />
        </div>

        {prompts ? (
          <div className="mt-5">
            <div className="flex gap-1 border-b border-neutral-200" role="tablist">
              {PROMPT_FORMS.map((f) => (
                <button
                  key={f}
                  type="button"
                  role="tab"
                  aria-selected={form === f}
                  onClick={() => onForm(f)}
                  className={`-mb-px border-b-2 px-4 py-2 text-sm transition-colors ${
                    form === f
                      ? "border-neutral-900 font-medium text-neutral-900"
                      : "border-transparent text-neutral-500 hover:text-neutral-900"
                  }`}
                >
                  {t(`workbench.pipeline.forms.${f}`)}
                </button>
              ))}
            </div>
            <div className="mt-3">
              {promptData.status === "loading" ? <Loading /> : null}
              {promptData.status === "unavailable" ? <DegradeBox /> : null}
              {promptData.status === "error" ? (
                <ErrorBox message={promptData.message} code={promptData.code} />
              ) : null}
              {promptData.status === "ready" ? (
                <pre className="max-h-96 overflow-auto rounded-lg bg-neutral-900 p-4 text-xs leading-relaxed text-neutral-100">
                  {JSON.stringify(promptData.data, null, 2)}
                </pre>
              ) : null}
            </div>
          </div>
        ) : (
          <div className="mt-4">
            <EmptyLine>{t("workbench.pipeline.promptsEmpty")}</EmptyLine>
          </div>
        )}
      </div>
    </section>
  );
}

function ShotRow({
  shot,
  busy,
  onSave,
}: {
  shot: StoryboardShot;
  busy: boolean;
  onSave: (shot: StoryboardShot) => void;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<StoryboardShot>(shot);
  const set = (patch: Partial<StoryboardShot>) => setDraft((d) => ({ ...d, ...patch }));

  return (
    <tr className="border-b border-neutral-100 align-top">
      <td className="py-2 pr-2 text-xs tabular-nums text-neutral-400">{draft.idx + 1}</td>
      <td className="py-2 pr-2">
        <input
          value={draft.shot_size ?? ""}
          onChange={(e) => set({ shot_size: e.target.value })}
          className={`${inputText} w-24`}
          aria-label={t("workbench.pipeline.shot")}
        />
      </td>
      <td className="py-2 pr-2">
        <input
          value={draft.visual ?? ""}
          onChange={(e) => set({ visual: e.target.value })}
          className={`${inputText} min-w-48`}
          aria-label={t("workbench.pipeline.visual")}
        />
      </td>
      <td className="py-2 pr-2">
        <input
          value={draft.action ?? ""}
          onChange={(e) => set({ action: e.target.value })}
          className={`${inputText} min-w-36`}
          aria-label={t("workbench.pipeline.action")}
        />
      </td>
      <td className="py-2 pr-2">
        <input
          value={draft.line ?? ""}
          onChange={(e) => set({ line: e.target.value })}
          className={`${inputText} min-w-36`}
          aria-label={t("workbench.pipeline.line")}
        />
      </td>
      <td className="py-2 pr-2">
        <input
          value={String(draft.duration ?? "")}
          onChange={(e) => set({ duration: e.target.value })}
          className={`${inputText} w-16`}
          aria-label={t("workbench.pipeline.duration")}
        />
      </td>
      <td className="py-2">
        <button type="button" disabled={busy} onClick={() => onSave(draft)} className={btnSecondary}>
          {busy ? t("workbench.saving") : t("workbench.pipeline.saveShot")}
        </button>
      </td>
    </tr>
  );
}

// ---- 容器：接 API ----

export default function PipelinePanel() {
  const { t } = useTranslation();

  const [projects, setProjects] = useState<Loadable<Project[]>>({ status: "idle" });
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [scenes, setScenes] = useState<Loadable<Scene[]>>({ status: "idle" });
  const [selectedSceneId, setSelectedSceneId] = useState("");

  const [storyboard, setStoryboard] = useState<Loadable<Storyboard>>({ status: "idle" });
  const [sbBusy, setSbBusy] = useState(false);
  const [sbNote, setSbNote] = useState<Note>(null);
  const [shotBusyIdx, setShotBusyIdx] = useState<number | null>(null);

  const [prompts, setPrompts] = useState<{ id: string } | null>(null);
  const [promptBusy, setPromptBusy] = useState(false);
  const [promptNote, setPromptNote] = useState<Note>(null);
  const [form, setForm] = useState<PromptForm>("image");
  const [promptData, setPromptData] = useState<Loadable<unknown>>({ status: "idle" });
  const [promptCache, setPromptCache] = useState<Partial<Record<PromptForm, unknown>>>({});
  const [downloadBusy, setDownloadBusy] = useState(false);
  const [downloadNote, setDownloadNote] = useState<Note>(null);

  useEffect(() => {
    setProjects({ status: "loading" });
    api
      .listProjects()
      .then((r) => setProjects({ status: "ready", data: r }))
      .catch((e: unknown) => setProjects(mapApiError(e)));
  }, []);

  useEffect(() => {
    if (!selectedProjectId) {
      setScenes({ status: "idle" });
      return;
    }
    setScenes({ status: "loading" });
    api
      .listScenes(selectedProjectId)
      .then((r) => setScenes({ status: "ready", data: r }))
      .catch((e: unknown) => setScenes(mapApiError(e)));
  }, [selectedProjectId]);

  const loadForm = async (psId: string, f: PromptForm) => {
    if (promptCache[f] !== undefined) {
      setPromptData({ status: "ready", data: promptCache[f] });
      return;
    }
    setPromptData({ status: "loading" });
    try {
      const data = await api.getPrompt(psId, f);
      setPromptCache((c) => ({ ...c, [f]: data }));
      setPromptData({ status: "ready", data });
    } catch (e) {
      setPromptData(mapApiError(e));
    }
  };

  const generateStoryboard = async () => {
    if (!selectedSceneId) return;
    setSbBusy(true);
    setSbNote(null);
    setPrompts(null);
    setPromptData({ status: "idle" });
    setPromptCache({});
    try {
      const sb = normalizeStoryboard(await api.genStoryboard(selectedSceneId));
      setStoryboard({ status: "ready", data: sb });
    } catch (e) {
      setStoryboard(mapApiError(e));
      setSbNote(noteFromError(e));
    } finally {
      setSbBusy(false);
    }
  };

  const updateShot = async (shot: StoryboardShot) => {
    if (storyboard.status !== "ready") return;
    const sb = storyboard.data;
    setShotBusyIdx(shot.idx);
    setSbNote(null);
    try {
      await api.updateShot(sb.id, shot.idx, shot);
      setStoryboard({
        status: "ready",
        data: { ...sb, shots: (sb.shots ?? []).map((s) => (s.idx === shot.idx ? shot : s)) },
      });
      setSbNote({ ok: t("workbench.pipeline.shotSaved") });
    } catch (e) {
      setSbNote(noteFromError(e));
    } finally {
      setShotBusyIdx(null);
    }
  };

  const generatePrompts = async () => {
    if (storyboard.status !== "ready") return;
    setPromptBusy(true);
    setPromptNote(null);
    try {
      const ref = await api.genPrompts(storyboard.data.id);
      const ps = { id: String(ref.id) };
      setPrompts(ps);
      await loadForm(ps.id, form);
    } catch (e) {
      setPromptNote(noteFromError(e));
    } finally {
      setPromptBusy(false);
    }
  };

  const switchForm = (f: PromptForm) => {
    setForm(f);
    if (prompts) void loadForm(prompts.id, f);
  };

  const download = async () => {
    if (!prompts) return;
    setDownloadBusy(true);
    setDownloadNote(null);
    try {
      const entries = await Promise.all(
        PROMPT_FORMS.map(async (f) => [f, await api.getPrompt(prompts.id, f)] as const),
      );
      downloadJson(`juchuang-prompts-${prompts.id}.json`, {
        id: prompts.id,
        forms: Object.fromEntries(entries),
      });
      setDownloadNote({ ok: t("workbench.pipeline.downloaded") });
    } catch (e) {
      setDownloadNote(noteFromError(e));
    } finally {
      setDownloadBusy(false);
    }
  };

  return (
    <PipelineView
      projects={projects}
      selectedProjectId={selectedProjectId}
      onSelectProject={setSelectedProjectId}
      scenes={scenes}
      selectedSceneId={selectedSceneId}
      onSelectScene={setSelectedSceneId}
      storyboard={storyboard}
      onGenerateStoryboard={() => void generateStoryboard()}
      sbBusy={sbBusy}
      sbNote={sbNote}
      onUpdateShot={(shot) => void updateShot(shot)}
      shotBusyIdx={shotBusyIdx}
      prompts={prompts}
      onGenPrompts={() => void generatePrompts()}
      promptBusy={promptBusy}
      promptNote={promptNote}
      form={form}
      onForm={switchForm}
      promptData={promptData}
      onDownload={() => void download()}
      downloadBusy={downloadBusy}
      downloadNote={downloadNote}
    />
  );
}
