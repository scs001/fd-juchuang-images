/** 哲思 · 精神内核：接入徽标（linked 绿 / standalone 灰+原因）、缓存立场卡、场次/角色注入。 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  api,
  type Character,
  type KernelCard,
  type KernelStatus,
  type Project,
  type Scene,
} from "../../api/client";
import { Loadable, mapApiError, noteFromError, type Note } from "../../api/state";
import {
  btnPrimary,
  btnSecondary,
  EmptyLine,
  LoadBox,
  ModeBadge,
  NoteBox,
  Picker,
  SectionTitle,
} from "../../components/ui";

// ---- 视图（显式状态，可独立渲染降级态） ----

export function KernelView({
  status,
  onLink,
  linkBusy,
  linkNote,
  projects,
  selectedProjectId,
  onSelectProject,
  scenes,
  selectedSceneId,
  onSelectScene,
  characters,
  selectedCharacterId,
  onSelectCharacter,
  onInject,
  injectBusy,
  injectNote,
}: {
  status: Loadable<KernelStatus>;
  onLink: () => void;
  linkBusy: boolean;
  linkNote: Note;
  projects: Loadable<Project[]>;
  selectedProjectId: string;
  onSelectProject: (id: string) => void;
  scenes: Loadable<Scene[]>;
  selectedSceneId: string;
  onSelectScene: (id: string) => void;
  characters: Loadable<Character[]>;
  selectedCharacterId: string;
  onSelectCharacter: (id: string) => void;
  onInject: () => void;
  injectBusy: boolean;
  injectNote: Note;
}) {
  const { t } = useTranslation();
  const standalone =
    status.status === "ready" && status.data.mode !== "linked";

  return (
    <section className="space-y-8">
      <div>
        <SectionTitle>{t("workbench.kernel.heading")}</SectionTitle>
        <p className="mt-1 text-sm text-neutral-500">{t("workbench.kernel.hint")}</p>
      </div>

      {/* 接入状态 */}
      <div className="rounded-lg border border-neutral-200 bg-white p-5" data-testid="kernel-status">
        <div className="flex flex-wrap items-center gap-3">
          <LoadBox state={status}>
            {(s) => (
              <>
                <ModeBadge mode={s.mode} />
                <span className="text-sm text-neutral-500">
                  {t("workbench.kernel.cardCount", { count: s.card_count ?? 0 })}
                </span>
                {standalone && s.reason ? (
                  <span className="text-xs text-neutral-400">
                    {t("workbench.kernel.reasonLabel")}：{s.reason}
                  </span>
                ) : null}
              </>
            )}
          </LoadBox>
          <button
            type="button"
            disabled={linkBusy}
            onClick={onLink}
            className={`${btnPrimary} ml-auto`}
          >
            {linkBusy
              ? t("workbench.kernel.linking")
              : status.status === "ready" && status.data.mode === "linked"
                ? t("workbench.kernel.relink")
                : t("workbench.kernel.link")}
          </button>
        </div>
        <div className="mt-2">
          <NoteBox note={linkNote} />
        </div>

        {/* 缓存卡列表 */}
        <div className="mt-4">
          <LoadBox state={status}>
            {(s) => {
              const cards = s.cards ?? [];
              return cards.length === 0 ? (
                <EmptyLine>{t("workbench.kernel.cardsEmpty")}</EmptyLine>
              ) : (
                <ul className="space-y-2" data-testid="kernel-cards">
                  {cards.map((c: KernelCard) => (
                    <li key={c.id} className="rounded border border-neutral-200 px-3 py-2 text-sm">
                      <span className="text-neutral-400">{t("workbench.kernel.cardQuestion")}：</span>
                      <span className="text-neutral-800">{c.question ?? c.title ?? c.id}</span>
                      {c.position ? (
                        <span className="ml-2 text-neutral-500">
                          {t("workbench.kernel.cardPosition")}：{c.position}
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              );
            }}
          </LoadBox>
        </div>
      </div>

      {/* 内核注入 */}
      <div className="rounded-lg border border-neutral-200 bg-white p-5">
        <SectionTitle>{t("workbench.kernel.injectHeading")}</SectionTitle>
        <p className="mt-1 text-sm text-neutral-500">{t("workbench.kernel.injectHint")}</p>
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <Picker
            label={t("workbench.kernel.project")}
            state={projects}
            selectedId={selectedProjectId}
            onSelect={onSelectProject}
            labelOf={(p: Project) => p.title || p.id}
          />
          <Picker
            label={t("workbench.kernel.scene")}
            state={scenes}
            selectedId={selectedSceneId}
            onSelect={onSelectScene}
            labelOf={(s: Scene) => s.title || s.id.slice(0, 8)}
          />
          <Picker
            label={t("workbench.kernel.characterScope")}
            state={characters}
            selectedId={selectedCharacterId}
            onSelect={onSelectCharacter}
            labelOf={(c: Character) => c.name}
          />
        </div>
        {!selectedSceneId && !selectedCharacterId ? (
          <p className="mt-2 text-xs text-neutral-400">{t("workbench.kernel.pickSceneOrChar")}</p>
        ) : null}
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={injectBusy || !selectedProjectId || (!selectedSceneId && !selectedCharacterId)}
            onClick={onInject}
            className={btnPrimary}
          >
            {injectBusy ? t("workbench.kernel.injecting") : t("workbench.kernel.inject")}
          </button>
          <button
            type="button"
            onClick={() => {
              onSelectScene("");
              onSelectCharacter("");
            }}
            className={btnSecondary}
          >
            {t("workbench.kernel.clearPick")}
          </button>
        </div>
        <div className="mt-2">
          <NoteBox note={injectNote} />
        </div>
      </div>
    </section>
  );
}

// ---- 容器：接 API ----

export default function KernelPanel() {
  const { t } = useTranslation();

  const [status, setStatus] = useState<Loadable<KernelStatus>>({ status: "idle" });
  const [linkBusy, setLinkBusy] = useState(false);
  const [linkNote, setLinkNote] = useState<Note>(null);

  const [projects, setProjects] = useState<Loadable<Project[]>>({ status: "idle" });
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [scenes, setScenes] = useState<Loadable<Scene[]>>({ status: "idle" });
  const [characters, setCharacters] = useState<Loadable<Character[]>>({ status: "idle" });
  const [selectedSceneId, setSelectedSceneId] = useState("");
  const [selectedCharacterId, setSelectedCharacterId] = useState("");

  const [injectBusy, setInjectBusy] = useState(false);
  const [injectNote, setInjectNote] = useState<Note>(null);

  useEffect(() => {
    setStatus({ status: "loading" });
    api
      .kernelStatus()
      .then((s) => setStatus({ status: "ready", data: s }))
      .catch((e: unknown) => setStatus(mapApiError(e)));
    setProjects({ status: "loading" });
    api
      .listProjects()
      .then((r) => setProjects({ status: "ready", data: r }))
      .catch((e: unknown) => setProjects(mapApiError(e)));
  }, []);

  useEffect(() => {
    if (!selectedProjectId) {
      setScenes({ status: "idle" });
      setCharacters({ status: "idle" });
      return;
    }
    setScenes({ status: "loading" });
    setCharacters({ status: "loading" });
    api
      .listScenes(selectedProjectId)
      .then((r) => setScenes({ status: "ready", data: r }))
      .catch((e: unknown) => setScenes(mapApiError(e)));
    api
      .listCharacters(selectedProjectId)
      .then((r) => setCharacters({ status: "ready", data: r }))
      .catch((e: unknown) => setCharacters(mapApiError(e)));
  }, [selectedProjectId]);

  const link = async () => {
    setLinkBusy(true);
    setLinkNote(null);
    try {
      const s = await api.kernelLink();
      setStatus({ status: "ready", data: s });
      setLinkNote({ ok: t("workbench.kernel.linked") });
    } catch (e) {
      setLinkNote(noteFromError(e));
    } finally {
      setLinkBusy(false);
    }
  };

  const inject = async () => {
    if (!selectedProjectId) return;
    setInjectBusy(true);
    setInjectNote(null);
    try {
      await api.kernelInject(selectedProjectId, {
        ...(selectedSceneId ? { scene_id: selectedSceneId } : {}),
        ...(selectedCharacterId ? { character_id: selectedCharacterId } : {}),
      });
      setInjectNote({ ok: t("workbench.kernel.injected") });
      // 状态可能随之变化（如卡数/模式），刷新一次
      api
        .kernelStatus()
        .then((s) => setStatus({ status: "ready", data: s }))
        .catch(() => undefined);
    } catch (e) {
      setInjectNote(noteFromError(e));
    } finally {
      setInjectBusy(false);
    }
  };

  return (
    <KernelView
      status={status}
      onLink={() => void link()}
      linkBusy={linkBusy}
      linkNote={linkNote}
      projects={projects}
      selectedProjectId={selectedProjectId}
      onSelectProject={setSelectedProjectId}
      scenes={scenes}
      selectedSceneId={selectedSceneId}
      onSelectScene={setSelectedSceneId}
      characters={characters}
      selectedCharacterId={selectedCharacterId}
      onSelectCharacter={setSelectedCharacterId}
      onInject={() => void inject()}
      injectBusy={injectBusy}
      injectNote={injectNote}
    />
  );
}
