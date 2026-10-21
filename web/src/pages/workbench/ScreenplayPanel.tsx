/** 剧本 · 结构化创作：项目 → 角色卡（要素集+立场）→ 场次（冲突）→ 台词；版本时间线（存档/回滚/导出）。 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  api,
  conflictText,
  downloadJson,
  stanceText,
  zhesiSource,
  type Character,
  type Line,
  type Project,
  type Scene,
  type VersionEntry,
} from "../../api/client";
import { Loadable, mapApiError, noteFromError, type Note } from "../../api/state";
import {
  btnDanger,
  btnPrimary,
  btnSecondary,
  DegradeBox,
  EmptyLine,
  ErrorBox,
  inputText,
  LoadBox,
  Loading,
  NoteBox,
  SectionTitle,
  ZhesiBadge,
} from "../../components/ui";

// ---- 视图（显式状态，可独立渲染降级态；小表单草稿留在视图本地） ----

export interface CharacterPayload {
  editingId: string | null;
  name: string;
  appearance: Record<string, string>;
  stance?: string;
}

export function ScreenplayView({
  projects,
  onCreateProject,
  createBusy,
  createNote,
  selectedProjectId,
  onSelectProject,
  selectedProject,
  characters,
  onSaveCharacter,
  onDeleteCharacter,
  charBusy,
  charNote,
  scenes,
  onCreateScene,
  sceneCreateBusy,
  sceneCreateNote,
  selectedSceneId,
  onSelectScene,
  onSaveScene,
  sceneBusy,
  sceneNote,
  lines,
  onAddLine,
  onUpdateLine,
  onDeleteLine,
  lineBusy,
  versions,
  onSnapshot,
  onRestore,
  restoreBusyId,
  versionBusy,
  restoreNote,
  onExport,
  exportBusy,
  exportNote,
}: {
  projects: Loadable<Project[]>;
  onCreateProject: (b: { title: string; logline: string }) => void;
  createBusy: boolean;
  createNote: Note;
  selectedProjectId: string;
  onSelectProject: (id: string) => void;
  selectedProject: Project | null;
  characters: Loadable<Character[]>;
  onSaveCharacter: (b: CharacterPayload) => void;
  onDeleteCharacter: (id: string) => void;
  charBusy: boolean;
  charNote: Note;
  scenes: Loadable<Scene[]>;
  onCreateScene: (b: { title: string; conflict: string }) => void;
  sceneCreateBusy: boolean;
  sceneCreateNote: Note;
  selectedSceneId: string;
  onSelectScene: (id: string) => void;
  /** View 只回传被改过的字段：conflict 未动就不回传（保护哲思注入的元数据）。 */
  onSaveScene: (b: { title: string; conflict?: string }, conflictTouched: boolean) => void;
  sceneBusy: boolean;
  sceneNote: Note;
  lines: Loadable<Line[]>;
  onAddLine: (b: { character_id?: string; text: string }) => void;
  onUpdateLine: (lineId: string, b: { character_id?: string; text: string }) => void;
  onDeleteLine: (lineId: string) => void;
  lineBusy: boolean;
  versions: Loadable<VersionEntry[]>;
  onSnapshot: (label: string) => void;
  onRestore: (versionId: string) => void;
  restoreBusyId: string | null;
  versionBusy: boolean;
  restoreNote: Note;
  onExport: () => void;
  exportBusy: boolean;
  exportNote: Note;
}) {
  const { t } = useTranslation();
  return (
    <section className="space-y-8">
      <div>
        <SectionTitle>{t("workbench.screenplay.heading")}</SectionTitle>
        <p className="mt-1 text-sm text-neutral-500">{t("workbench.screenplay.hint")}</p>
      </div>

      <div className="grid gap-8 lg:grid-cols-[280px,1fr]">
        {/* 左：项目列表 + 新建 */}
        <div className="space-y-4">
          <NewProjectForm busy={createBusy} onSubmit={onCreateProject} />
          <NoteBox note={createNote} />
          <LoadBox state={projects}>
            {(list) =>
              list.length === 0 ? (
                <EmptyLine>{t("workbench.screenplay.projectsEmpty")}</EmptyLine>
              ) : (
                <ul className="space-y-2" data-testid="project-list">
                  {list.map((p) => (
                    <li key={p.id}>
                      <button
                        type="button"
                        onClick={() => onSelectProject(p.id)}
                        className={`w-full rounded-lg border px-3 py-2 text-left text-sm ${
                          p.id === selectedProjectId
                            ? "border-neutral-900 bg-white"
                            : "border-neutral-200 bg-white hover:border-neutral-400"
                        }`}
                      >
                        <span className="block font-medium text-neutral-900">
                          {p.title || t("workbench.untitled")}
                        </span>
                        {p.logline ? (
                          <span className="mt-0.5 block truncate text-xs text-neutral-500">{p.logline}</span>
                        ) : null}
                      </button>
                    </li>
                  ))}
                </ul>
              )
            }
          </LoadBox>
        </div>

        {/* 右：选中项目的编辑区 */}
        <div className="space-y-10">
          {!selectedProject ? (
            <EmptyLine>{t("workbench.screenplay.noProject")}</EmptyLine>
          ) : (
            <>
              <CharactersBlock
                characters={characters}
                onSave={onSaveCharacter}
                onDelete={onDeleteCharacter}
                busy={charBusy}
                note={charNote}
              />

              <ScenesBlock
                scenes={scenes}
                onCreate={onCreateScene}
                createBusy={sceneCreateBusy}
                createNote={sceneCreateNote}
                selectedSceneId={selectedSceneId}
                onSelect={onSelectScene}
              />

              {selectedSceneFrom(scenes, selectedSceneId) ? (
                <SceneEditorBlock
                  scene={selectedSceneFrom(scenes, selectedSceneId)!}
                  characters={characters}
                  lines={lines}
                  onSave={onSaveScene}
                  sceneBusy={sceneBusy}
                  sceneNote={sceneNote}
                  onAddLine={onAddLine}
                  onUpdateLine={onUpdateLine}
                  onDeleteLine={onDeleteLine}
                  lineBusy={lineBusy}
                />
              ) : null}

              <VersionsBlock
                versions={versions}
                onSnapshot={onSnapshot}
                onRestore={onRestore}
                restoreBusyId={restoreBusyId}
                versionBusy={versionBusy}
                restoreNote={restoreNote}
                onExport={onExport}
                exportBusy={exportBusy}
                exportNote={exportNote}
              />
            </>
          )}
        </div>
      </div>
    </section>
  );
}

function selectedSceneFrom(scenes: Loadable<Scene[]>, id: string): Scene | null {
  return scenes.status === "ready" ? (scenes.data.find((s) => s.id === id) ?? null) : null;
}

// ---- 新建项目 ----

function NewProjectForm({ busy, onSubmit }: { busy: boolean; onSubmit: (b: { title: string; logline: string }) => void }) {
  const { t } = useTranslation();
  const [title, setTitle] = useState("");
  const [logline, setLogline] = useState("");
  const submit = () => {
    if (!title.trim()) return;
    onSubmit({ title: title.trim(), logline: logline.trim() });
    setTitle("");
    setLogline("");
  };
  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-4">
      <SectionTitle>{t("workbench.screenplay.newProject")}</SectionTitle>
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder={t("workbench.screenplay.projectTitle")}
        className={`${inputText} mt-3`}
      />
      <textarea
        value={logline}
        onChange={(e) => setLogline(e.target.value)}
        placeholder={t("workbench.screenplay.projectLogline")}
        rows={2}
        className={`${inputText} mt-2`}
      />
      <button type="button" disabled={busy || !title.trim()} onClick={submit} className={`${btnPrimary} mt-3`}>
        {busy ? t("workbench.screenplay.creating") : t("workbench.screenplay.create")}
      </button>
    </div>
  );
}

// ---- 角色卡 ----

function CharactersBlock({
  characters,
  onSave,
  onDelete,
  busy,
  note,
}: {
  characters: Loadable<Character[]>;
  onSave: (b: CharacterPayload) => void;
  onDelete: (id: string) => void;
  busy: boolean;
  note: Note;
}) {
  const { t } = useTranslation();
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<Character | null>(null);

  const openNew = () => {
    setEditing(null);
    setEditorOpen(true);
  };
  const openEdit = (c: Character) => {
    setEditing(c);
    setEditorOpen(true);
  };

  return (
    <div>
      <div className="flex items-center justify-between">
        <SectionTitle>{t("workbench.screenplay.characters")}</SectionTitle>
        <button type="button" onClick={openNew} className={btnSecondary}>
          {t("workbench.screenplay.newCharacter")}
        </button>
      </div>
      <div className="mt-3">
        <NoteBox note={note} />
        {editorOpen ? (
          <CharacterEditor
            character={editing}
            busy={busy}
            onCancel={() => setEditorOpen(false)}
            onSave={(payload) => {
              onSave(payload);
              setEditorOpen(false);
            }}
          />
        ) : null}
        <LoadBox state={characters}>
          {(list) =>
            list.length === 0 ? (
              <EmptyLine>{t("workbench.screenplay.charactersEmpty")}</EmptyLine>
            ) : (
              <ul className="mt-3 grid gap-3 md:grid-cols-2" data-testid="character-list">
                {list.map((c) => {
                  const stance = stanceText(c.stance);
                  const src = zhesiSource(c.stance);
                  return (
                    <li key={c.id} className="rounded-lg border border-neutral-200 bg-white p-4">
                      <div className="flex items-start justify-between gap-2">
                        <h3 className="font-serif text-neutral-900">{c.name}</h3>
                        <div className="flex shrink-0 gap-2">
                          <button type="button" onClick={() => openEdit(c)} className={btnSecondary}>
                            {t("workbench.screenplay.edit")}
                          </button>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => onDelete(c.id)}
                            className={btnDanger}
                          >
                            {t("workbench.screenplay.delete")}
                          </button>
                        </div>
                      </div>
                      {stance ? (
                        <p className="mt-1 text-sm text-neutral-600">
                          <span className="text-neutral-400">{t("workbench.screenplay.stanceLabel")}：</span>
                          {stance}
                          <ZhesiBadge meta={src} />
                        </p>
                      ) : null}
                      <dl className="mt-2 flex flex-wrap gap-1.5">
                        {Object.entries(c.appearance ?? {}).map(([k, v]) => (
                          <span
                            key={k}
                            className="rounded border border-neutral-200 bg-neutral-50 px-1.5 py-0.5 text-xs text-neutral-600"
                          >
                            {k}: {v}
                          </span>
                        ))}
                      </dl>
                    </li>
                  );
                })}
              </ul>
            )
          }
        </LoadBox>
      </div>
    </div>
  );
}

/** 角色编辑器：姓名 + 要素集键值对（≥2 键）+ 立场。 */
function CharacterEditor({
  character,
  busy,
  onSave,
  onCancel,
}: {
  character: Character | null;
  busy: boolean;
  onSave: (b: CharacterPayload) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState(character?.name ?? "");
  const [pairs, setPairs] = useState<{ key: string; value: string }[]>(() => {
    const entries = Object.entries(character?.appearance ?? {}).map(([key, value]) => ({
      key,
      value: String(value),
    }));
    while (entries.length < 2) entries.push({ key: "", value: "" });
    return entries;
  });
  const [stance, setStance] = useState(stanceText(character?.stance));
  const [err, setErr] = useState<string | null>(null);

  const setPair = (i: number, patch: { key?: string; value?: string }) => {
    setPairs((ps) => ps.map((p, j) => (j === i ? { ...p, ...patch } : p)));
  };

  const submit = () => {
    if (!name.trim()) {
      setErr(t("workbench.screenplay.needName"));
      return;
    }
    const filled = pairs.filter((p) => p.key.trim());
    if (filled.length < 2) {
      setErr(t("workbench.screenplay.needTwoKeys"));
      return;
    }
    const appearance = Object.fromEntries(filled.map((p) => [p.key.trim(), p.value.trim()]));
    onSave({
      editingId: character?.id ?? null,
      name: name.trim(),
      appearance,
      stance: stance.trim() || undefined,
    });
  };

  return (
    <div className="mb-3 rounded-lg border border-neutral-300 bg-white p-4">
      <h3 className="font-serif text-neutral-900">
        {character ? t("workbench.screenplay.editCharacter") : t("workbench.screenplay.newCharacter")}
      </h3>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder={t("workbench.screenplay.charName")}
        className={`${inputText} mt-3`}
      />
      <p className="mt-3 text-xs text-neutral-500">{t("workbench.screenplay.appearance")}</p>
      <div className="mt-1 space-y-2">
        {pairs.map((p, i) => (
          <div key={i} className="flex gap-2">
            <input
              value={p.key}
              onChange={(e) => setPair(i, { key: e.target.value })}
              placeholder={t("workbench.screenplay.appearanceKey")}
              className={`${inputText} w-1/3`}
            />
            <input
              value={p.value}
              onChange={(e) => setPair(i, { value: e.target.value })}
              placeholder={t("workbench.screenplay.appearanceValue")}
              className={inputText}
            />
            <button
              type="button"
              onClick={() => setPairs((ps) => ps.filter((_, j) => j !== i))}
              className={btnDanger}
              aria-label={t("workbench.screenplay.removePair")}
            >
              ×
            </button>
          </div>
        ))}
      </div>
      <button type="button" onClick={() => setPairs((ps) => [...ps, { key: "", value: "" }])} className={`${btnSecondary} mt-2`}>
        {t("workbench.screenplay.addPair")}
      </button>
      <textarea
        value={stance}
        onChange={(e) => setStance(e.target.value)}
        placeholder={t("workbench.screenplay.stancePlaceholder")}
        rows={2}
        className={`${inputText} mt-3`}
      />
      {err ? <ErrorBox message={err} /> : null}
      <div className="mt-3 flex gap-3">
        <button type="button" disabled={busy} onClick={submit} className={btnPrimary}>
          {busy ? t("workbench.saving") : t("workbench.screenplay.save")}
        </button>
        <button type="button" onClick={onCancel} className={btnSecondary}>
          {t("workbench.screenplay.cancel")}
        </button>
      </div>
    </div>
  );
}

// ---- 场次 ----

function ScenesBlock({
  scenes,
  onCreate,
  createBusy,
  createNote,
  selectedSceneId,
  onSelect,
}: {
  scenes: Loadable<Scene[]>;
  onCreate: (b: { title: string; conflict: string }) => void;
  createBusy: boolean;
  createNote: Note;
  selectedSceneId: string;
  onSelect: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [title, setTitle] = useState("");
  const [conflict, setConflict] = useState("");

  const submit = () => {
    if (!title.trim()) return;
    onCreate({ title: title.trim(), conflict: conflict.trim() });
    setTitle("");
    setConflict("");
  };

  return (
    <div>
      <SectionTitle>{t("workbench.screenplay.scenes")}</SectionTitle>
      <div className="mt-3 rounded-lg border border-neutral-200 bg-white p-4">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={t("workbench.screenplay.sceneTitle")}
          className={inputText}
        />
        <textarea
          value={conflict}
          onChange={(e) => setConflict(e.target.value)}
          placeholder={t("workbench.screenplay.conflictPlaceholder")}
          rows={2}
          className={`${inputText} mt-2`}
        />
        <button type="button" disabled={createBusy || !title.trim()} onClick={submit} className={`${btnPrimary} mt-3`}>
          {createBusy ? t("workbench.saving") : t("workbench.screenplay.newScene")}
        </button>
        <div className="mt-2">
          <NoteBox note={createNote} />
        </div>
      </div>
      <div className="mt-3">
        <LoadBox state={scenes}>
          {(list) =>
            list.length === 0 ? (
              <EmptyLine>{t("workbench.screenplay.scenesEmpty")}</EmptyLine>
            ) : (
              <ul className="space-y-2" data-testid="scene-list">
                {list.map((s) => {
                  const c = conflictText(s.conflict);
                  return (
                    <li key={s.id}>
                      <button
                        type="button"
                        onClick={() => onSelect(s.id)}
                        className={`w-full rounded-lg border px-3 py-2 text-left text-sm ${
                          s.id === selectedSceneId
                            ? "border-neutral-900 bg-white"
                            : "border-neutral-200 bg-white hover:border-neutral-400"
                        }`}
                      >
                        <span className="font-medium text-neutral-900">
                          {s.title || t("workbench.untitled")}
                        </span>
                        {c ? (
                          <span className="mt-0.5 flex items-center gap-1 text-xs text-neutral-500">
                            <span className="truncate">{c}</span>
                            <ZhesiBadge meta={zhesiSource(s.conflict)} />
                          </span>
                        ) : null}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )
          }
        </LoadBox>
      </div>
    </div>
  );
}

// ---- 场次编辑器 + 台词 ----

function SceneEditorBlock({
  scene,
  characters,
  lines,
  onSave,
  sceneBusy,
  sceneNote,
  onAddLine,
  onUpdateLine,
  onDeleteLine,
  lineBusy,
}: {
  scene: Scene;
  characters: Loadable<Character[]>;
  lines: Loadable<Line[]>;
  onSave: (b: { title: string; conflict?: string }, conflictTouched: boolean) => void;
  sceneBusy: boolean;
  sceneNote: Note;
  onAddLine: (b: { character_id?: string; text: string }) => void;
  onUpdateLine: (lineId: string, b: { character_id?: string; text: string }) => void;
  onDeleteLine: (lineId: string) => void;
  lineBusy: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="rounded-lg border border-neutral-900/10 bg-white p-5" data-testid="scene-editor">
      <SceneMetaEditor key={scene.id} scene={scene} busy={sceneBusy} onSave={onSave} />
      <div className="mt-2">
        <NoteBox note={sceneNote} />
      </div>

      <div className="mt-6">
        <h3 className="font-serif text-neutral-900">{t("workbench.screenplay.lines")}</h3>
        <div className="mt-3">
          {lines.status === "loading" ? <Loading /> : null}
          {lines.status === "unavailable" ? <DegradeBox /> : null}
          {lines.status === "error" ? <ErrorBox message={lines.message} code={lines.code} /> : null}
          {lines.status === "ready" ? (
            lines.data.length === 0 ? (
              <EmptyLine>{t("workbench.screenplay.linesEmpty")}</EmptyLine>
            ) : (
              <ul className="space-y-2">
                {lines.data.map((l) => (
                  <LineRow
                    key={l.id}
                    line={l}
                    characters={characters.status === "ready" ? characters.data : []}
                    busy={lineBusy}
                    onUpdate={onUpdateLine}
                    onDelete={onDeleteLine}
                  />
                ))}
              </ul>
            )
          ) : null}
          <AddLineForm
            characters={characters.status === "ready" ? characters.data : []}
            busy={lineBusy}
            onAdd={onAddLine}
          />
        </div>
      </div>
    </div>
  );
}

/** 场次元数据编辑：标题 + 冲突（未改动 conflict 就不回传，保护哲思注入元数据）。 */
function SceneMetaEditor({
  scene,
  busy,
  onSave,
}: {
  scene: Scene;
  busy: boolean;
  onSave: (b: { title: string; conflict?: string }, conflictTouched: boolean) => void;
}) {
  const { t } = useTranslation();
  const [title, setTitle] = useState(scene.title ?? "");
  const [conflict, setConflict] = useState(conflictText(scene.conflict));
  const [touched, setTouched] = useState(false);
  const src = zhesiSource(scene.conflict);

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-serif text-lg text-neutral-900">{t("workbench.screenplay.sceneEditor")}</h3>
        <ZhesiBadge meta={src} />
        {src && src.cardIds.length ? (
          <span className="text-xs text-neutral-400">{t("workbench.zhesiCards", { ids: src.cardIds.join(", ") })}</span>
        ) : null}
      </div>
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder={t("workbench.screenplay.sceneTitle")}
        className={`${inputText} mt-3`}
      />
      <textarea
        value={conflict}
        onChange={(e) => {
          setConflict(e.target.value);
          setTouched(true);
        }}
        placeholder={t("workbench.screenplay.conflictPlaceholder")}
        rows={2}
        className={`${inputText} mt-2`}
      />
      <p className="mt-1 text-xs text-neutral-400">{t("workbench.screenplay.conflict")}</p>
      <button
        type="button"
        disabled={busy}
        onClick={() => onSave({ title: title.trim(), ...(touched ? { conflict: conflict.trim() } : {}) }, touched)}
        className={`${btnPrimary} mt-3`}
      >
        {busy ? t("workbench.saving") : t("workbench.screenplay.saveScene")}
      </button>
    </div>
  );
}

function LineRow({
  line,
  characters,
  busy,
  onUpdate,
  onDelete,
}: {
  line: Line;
  characters: Character[];
  busy: boolean;
  onUpdate: (lineId: string, b: { character_id?: string; text: string }) => void;
  onDelete: (lineId: string) => void;
}) {
  const { t } = useTranslation();
  const [characterId, setCharacterId] = useState(line.character_id ?? "");
  const [text, setText] = useState(line.text ?? "");

  return (
    <li className="flex flex-wrap items-center gap-2">
      <select
        value={characterId}
        onChange={(e) => setCharacterId(e.target.value)}
        className="w-36 rounded border border-neutral-300 bg-white px-2 py-1.5 text-sm"
        aria-label={t("workbench.screenplay.character")}
      >
        <option value="">{t("workbench.screenplay.narrator")}</option>
        {characters.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={t("workbench.screenplay.linePlaceholder")}
        className="min-w-40 flex-1 rounded border border-neutral-300 px-2 py-1.5 text-sm"
      />
      <button
        type="button"
        disabled={busy || !text.trim()}
        onClick={() => onUpdate(line.id, { ...(characterId ? { character_id: characterId } : {}), text: text.trim() })}
        className={btnSecondary}
      >
        {t("workbench.screenplay.save")}
      </button>
      <button type="button" disabled={busy} onClick={() => onDelete(line.id)} className={btnDanger}>
        {t("workbench.screenplay.delete")}
      </button>
    </li>
  );
}

function AddLineForm({
  characters,
  busy,
  onAdd,
}: {
  characters: Character[];
  busy: boolean;
  onAdd: (b: { character_id?: string; text: string }) => void;
}) {
  const { t } = useTranslation();
  const [characterId, setCharacterId] = useState("");
  const [text, setText] = useState("");
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <select
        value={characterId}
        onChange={(e) => setCharacterId(e.target.value)}
        className="w-36 rounded border border-neutral-300 bg-white px-2 py-1.5 text-sm"
        aria-label={t("workbench.screenplay.character")}
      >
        <option value="">{t("workbench.screenplay.narrator")}</option>
        {characters.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={t("workbench.screenplay.linePlaceholder")}
        className="min-w-40 flex-1 rounded border border-neutral-300 px-2 py-1.5 text-sm"
      />
      <button
        type="button"
        disabled={busy || !text.trim()}
        onClick={() => {
          onAdd({ ...(characterId ? { character_id: characterId } : {}), text: text.trim() });
          setText("");
        }}
        className={btnSecondary}
      >
        {t("workbench.screenplay.addLine")}
      </button>
    </div>
  );
}

// ---- 版本时间线 ----

function VersionsBlock({
  versions,
  onSnapshot,
  onRestore,
  restoreBusyId,
  versionBusy,
  restoreNote,
  onExport,
  exportBusy,
  exportNote,
}: {
  versions: Loadable<VersionEntry[]>;
  onSnapshot: (label: string) => void;
  onRestore: (versionId: string) => void;
  restoreBusyId: string | null;
  versionBusy: boolean;
  restoreNote: Note;
  onExport: () => void;
  exportBusy: boolean;
  exportNote: Note;
}) {
  const { t } = useTranslation();
  const [label, setLabel] = useState("");
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SectionTitle>{t("workbench.screenplay.versions")}</SectionTitle>
        <button type="button" disabled={exportBusy} onClick={onExport} className={btnSecondary}>
          {exportBusy ? t("workbench.screenplay.exporting") : t("workbench.screenplay.export")}
        </button>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder={t("workbench.screenplay.versionLabel")}
          className={`${inputText} max-w-xs`}
        />
        <button
          type="button"
          disabled={versionBusy}
          onClick={() => {
            onSnapshot(label.trim());
            setLabel("");
          }}
          className={btnPrimary}
        >
          {versionBusy ? t("workbench.screenplay.snapshotting") : t("workbench.screenplay.snapshot")}
        </button>
        <div className="w-full space-y-2">
          <NoteBox note={restoreNote} />
          <NoteBox note={exportNote} />
        </div>
      </div>
      <div className="mt-3">
        <LoadBox state={versions}>
          {(list) =>
            list.length === 0 ? (
              <EmptyLine>{t("workbench.screenplay.versionsEmpty")}</EmptyLine>
            ) : (
              <ol className="mt-3 space-y-2 border-l-2 border-neutral-200 pl-4" data-testid="version-list">
                {list.map((v) => (
                  <li key={v.id} className="relative rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm">
                    <span className="absolute -left-[22px] top-4 h-2 w-2 rounded-full bg-neutral-400" />
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <span className="font-medium text-neutral-900">
                          {v.label || t("workbench.untitled")}
                        </span>
                        <span className="ml-2 text-xs text-neutral-400">
                          {v.created_at ?? ""}
                          <span className="ml-1 font-mono">{v.id.slice(0, 8)}</span>
                        </span>
                      </div>
                      <button
                        type="button"
                        disabled={restoreBusyId !== null}
                        onClick={() => onRestore(v.id)}
                        className={btnSecondary}
                      >
                        {restoreBusyId === v.id ? t("workbench.screenplay.restoring") : t("workbench.screenplay.restore")}
                      </button>
                    </div>
                  </li>
                ))}
              </ol>
            )
          }
        </LoadBox>
      </div>
    </div>
  );
}

// ---- 容器：接 API ----

export default function ScreenplayPanel() {
  const { t } = useTranslation();

  const [projects, setProjects] = useState<Loadable<Project[]>>({ status: "idle" });
  const [createBusy, setCreateBusy] = useState(false);
  const [createNote, setCreateNote] = useState<Note>(null);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);

  const [characters, setCharacters] = useState<Loadable<Character[]>>({ status: "idle" });
  const [charBusy, setCharBusy] = useState(false);
  const [charNote, setCharNote] = useState<Note>(null);

  const [scenes, setScenes] = useState<Loadable<Scene[]>>({ status: "idle" });
  const [sceneCreateBusy, setSceneCreateBusy] = useState(false);
  const [sceneCreateNote, setSceneCreateNote] = useState<Note>(null);
  const [selectedSceneId, setSelectedSceneId] = useState("");
  const [sceneBusy, setSceneBusy] = useState(false);
  const [sceneNote, setSceneNote] = useState<Note>(null);

  const [lines, setLines] = useState<Loadable<Line[]>>({ status: "idle" });
  const [lineBusy, setLineBusy] = useState(false);

  const [versions, setVersions] = useState<Loadable<VersionEntry[]>>({ status: "idle" });
  const [versionBusy, setVersionBusy] = useState(false);
  const [restoreBusyId, setRestoreBusyId] = useState<string | null>(null);
  const [restoreNote, setRestoreNote] = useState<Note>(null);
  const [exportBusy, setExportBusy] = useState(false);
  const [exportNote, setExportNote] = useState<Note>(null);

  const loadProjects = async () => {
    setProjects({ status: "loading" });
    try {
      setProjects({ status: "ready", data: await api.listProjects() });
    } catch (e) {
      setProjects(mapApiError(e));
    }
  };

  const loadProjectDetail = async (pid: string) => {
    setSelectedProjectId(pid);
    setSelectedSceneId("");
    setLines({ status: "idle" });
    if (!pid) {
      setSelectedProject(null);
      setCharacters({ status: "idle" });
      setScenes({ status: "idle" });
      setVersions({ status: "idle" });
      return;
    }
    setCharacters((c) => (c.status === "ready" ? { ...c, status: "loading", data: c.data } : { status: "loading" }));
    setScenes({ status: "loading" });
    setVersions({ status: "loading" });
    try {
      const list = await api.listProjects();
      setProjects({ status: "ready", data: list });
      setSelectedProject(list.find((p) => p.id === pid) ?? null);
    } catch {
      /* 项目列表失败不阻断已选项目的编辑区 */
    }
    api
      .listCharacters(pid)
      .then((r) => setCharacters({ status: "ready", data: r }))
      .catch((e: unknown) => setCharacters(mapApiError(e)));
    api
      .listScenes(pid)
      .then((r) => setScenes({ status: "ready", data: r }))
      .catch((e: unknown) => setScenes(mapApiError(e)));
    api
      .listVersions(pid)
      .then((r) => setVersions({ status: "ready", data: sortVersions(r) }))
      .catch((e: unknown) => setVersions(mapApiError(e)));
  };

  useEffect(() => {
    void loadProjects();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selectedSceneId) {
      setLines({ status: "idle" });
      return;
    }
    setLines({ status: "loading" });
    api
      .listLines(selectedSceneId)
      .then((r) => setLines({ status: "ready", data: r }))
      .catch((e: unknown) => setLines(mapApiError(e)));
  }, [selectedSceneId]);

  const createProject = async (b: { title: string; logline: string }) => {
    setCreateBusy(true);
    setCreateNote(null);
    try {
      const p = await api.createProject({ title: b.title, ...(b.logline ? { logline: b.logline } : {}) });
      setCreateNote({ ok: t("workbench.saved") });
      await loadProjects();
      await loadProjectDetail(p.id);
    } catch (e) {
      setCreateNote(noteFromError(e));
    } finally {
      setCreateBusy(false);
    }
  };

  const saveCharacter = async (b: CharacterPayload) => {
    if (!selectedProjectId) return;
    setCharBusy(true);
    setCharNote(null);
    try {
      const payload = { name: b.name, appearance: b.appearance, ...(b.stance ? { stance: b.stance } : {}) };
      if (b.editingId) await api.updateCharacter(selectedProjectId, b.editingId, payload);
      else await api.createCharacter(selectedProjectId, payload);
      setCharNote({ ok: t("workbench.saved") });
      setCharacters({ status: "ready", data: await api.listCharacters(selectedProjectId) });
    } catch (e) {
      setCharNote(noteFromError(e));
    } finally {
      setCharBusy(false);
    }
  };

  const deleteCharacter = async (id: string) => {
    if (!selectedProjectId) return;
    setCharBusy(true);
    setCharNote(null);
    try {
      await api.deleteCharacter(selectedProjectId, id);
      setCharacters({ status: "ready", data: await api.listCharacters(selectedProjectId) });
    } catch (e) {
      setCharNote(noteFromError(e));
    } finally {
      setCharBusy(false);
    }
  };

  const createScene = async (b: { title: string; conflict: string }) => {
    if (!selectedProjectId) return;
    setSceneCreateBusy(true);
    setSceneCreateNote(null);
    try {
      await api.createScene(selectedProjectId, { title: b.title, ...(b.conflict ? { conflict: b.conflict } : {}) });
      setSceneCreateNote({ ok: t("workbench.saved") });
      setScenes({ status: "ready", data: await api.listScenes(selectedProjectId) });
    } catch (e) {
      setSceneCreateNote(noteFromError(e));
    } finally {
      setSceneCreateBusy(false);
    }
  };

  const saveScene = async (sceneId: string, b: { title: string; conflict?: string }) => {
    setSceneBusy(true);
    setSceneNote(null);
    try {
      const updated = await api.updateScene(selectedProjectId, sceneId, b);
      setScenes((s) =>
        s.status === "ready"
          ? { status: "ready", data: s.data.map((x) => (x.id === sceneId ? { ...x, ...updated } : x)) }
          : s,
      );
      setSceneNote({ ok: t("workbench.saved") });
    } catch (e) {
      setSceneNote(noteFromError(e));
    } finally {
      setSceneBusy(false);
    }
  };

  const addLine = async (b: { character_id?: string; text: string }) => {
    if (!selectedSceneId) return;
    setLineBusy(true);
    try {
      await api.createLine(selectedSceneId, b);
      setLines({ status: "ready", data: await api.listLines(selectedSceneId) });
    } catch (e) {
      setSceneNote(noteFromError(e));
    } finally {
      setLineBusy(false);
    }
  };

  const updateLine = async (lineId: string, b: { character_id?: string; text: string }) => {
    if (!selectedSceneId) return;
    setLineBusy(true);
    try {
      await api.updateLine(selectedSceneId, lineId, b);
      setLines({ status: "ready", data: await api.listLines(selectedSceneId) });
    } catch (e) {
      setSceneNote(noteFromError(e));
    } finally {
      setLineBusy(false);
    }
  };

  const deleteLine = async (lineId: string) => {
    if (!selectedSceneId) return;
    setLineBusy(true);
    try {
      await api.deleteLine(selectedSceneId, lineId);
      setLines({ status: "ready", data: await api.listLines(selectedSceneId) });
    } catch (e) {
      setSceneNote(noteFromError(e));
    } finally {
      setLineBusy(false);
    }
  };

  const snapshot = async (label: string) => {
    if (!selectedProjectId) return;
    setVersionBusy(true);
    setRestoreNote(null);
    try {
      await api.createVersion(selectedProjectId, label || undefined);
      setVersions({ status: "ready", data: sortVersions(await api.listVersions(selectedProjectId)) });
      setRestoreNote({ ok: t("workbench.screenplay.snapshotted") });
    } catch (e) {
      setRestoreNote(noteFromError(e));
    } finally {
      setVersionBusy(false);
    }
  };

  const restore = async (versionId: string) => {
    if (!selectedProjectId) return;
    setRestoreBusyId(versionId);
    setRestoreNote(null);
    try {
      await api.restoreVersion(selectedProjectId, versionId);
      await loadProjectDetail(selectedProjectId);
      setRestoreNote({ ok: t("workbench.screenplay.restored") });
    } catch (e) {
      setRestoreNote(noteFromError(e));
    } finally {
      setRestoreBusyId(null);
    }
  };

  const exportJson = async () => {
    if (!selectedProjectId) return;
    setExportBusy(true);
    setExportNote(null);
    try {
      const data = await api.exportProject(selectedProjectId);
      downloadJson(`juchuang-project-${selectedProjectId}.json`, data);
      setExportNote({ ok: t("workbench.screenplay.exported") });
    } catch (e) {
      setExportNote(noteFromError(e));
    } finally {
      setExportBusy(false);
    }
  };

  return (
    <ScreenplayView
      projects={projects}
      onCreateProject={(b) => void createProject(b)}
      createBusy={createBusy}
      createNote={createNote}
      selectedProjectId={selectedProjectId}
      onSelectProject={(id) => void loadProjectDetail(id)}
      selectedProject={selectedProject}
      characters={characters}
      onSaveCharacter={(b) => void saveCharacter(b)}
      onDeleteCharacter={(id) => void deleteCharacter(id)}
      charBusy={charBusy}
      charNote={charNote}
      scenes={scenes}
      onCreateScene={(b) => void createScene(b)}
      sceneCreateBusy={sceneCreateBusy}
      sceneCreateNote={sceneCreateNote}
      selectedSceneId={selectedSceneId}
      onSelectScene={setSelectedSceneId}
      onSaveScene={(b) => {
        if (selectedSceneId) void saveScene(selectedSceneId, b);
      }}
      sceneBusy={sceneBusy}
      sceneNote={sceneNote}
      lines={lines}
      onAddLine={(b) => void addLine(b)}
      onUpdateLine={(id, b) => void updateLine(id, b)}
      onDeleteLine={(id) => void deleteLine(id)}
      lineBusy={lineBusy}
      versions={versions}
      onSnapshot={(label) => void snapshot(label)}
      onRestore={(vid) => void restore(vid)}
      restoreBusyId={restoreBusyId}
      versionBusy={versionBusy}
      restoreNote={restoreNote}
      onExport={() => void exportJson()}
      exportBusy={exportBusy}
      exportNote={exportNote}
    />
  );
}

function sortVersions(list: VersionEntry[]): VersionEntry[] {
  return [...list].sort((a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")));
}
