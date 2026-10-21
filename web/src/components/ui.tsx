/** 工作台共用小部件：状态徽标、降级/错误/加载盒、分节标题、选择器。无外部 UI 库。 */
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { ZhesiSource } from "../api/client";
import { Loadable } from "../api/state";

export function Loading() {
  const { t } = useTranslation();
  return <p className="animate-pulse text-sm text-neutral-400">{t("workbench.loading")}</p>;
}

/** 「该能力接线中」降级盒（后端并行开发：5xx/超时/404）。 */
export function DegradeBox({ extra }: { extra?: ReactNode }) {
  const { t } = useTranslation();
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
      <p>{t("workbench.unavailable")}</p>
      {extra ? <div className="mt-1 text-xs text-amber-700">{extra}</div> : null}
    </div>
  );
}

/** 业务错误盒（4xx 等）；401 追加「请先在顶栏设置访问令牌」。 */
export function ErrorBox({ message, code }: { message: string; code?: number }) {
  const { t } = useTranslation();
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
      <p>
        {t("workbench.error")}
        {message ? `：${message}` : ""}
      </p>
      {code === 401 ? <p className="mt-1 text-xs">{t("workbench.tokenHint")}</p> : null}
    </div>
  );
}

/** 操作反馈 Note 三态渲染。 */
export function NoteBox({ note }: { note: { ok: string } | { err: string } | { unavailable: true } | null }) {
  const { t } = useTranslation();
  if (!note) return null;
  if ("ok" in note) {
    return <p className="text-sm text-green-700">{note.ok}</p>;
  }
  if ("err" in note) return <ErrorBox message={note.err} />;
  return <DegradeBox />;
}

/** Loadable 五态统一渲染：idle 空、loading、unavailable 降级、error 报错、ready 渲染 children。 */
export function LoadBox<T>({
  state,
  children,
}: {
  state: Loadable<T>;
  children: (data: T) => ReactNode;
}) {
  if (state.status === "idle") return null;
  if (state.status === "loading") return <Loading />;
  if (state.status === "unavailable") return <DegradeBox />;
  if (state.status === "error") return <ErrorBox message={state.message} code={state.code} />;
  return <>{children(state.data)}</>;
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return <h2 className="font-serif text-lg text-neutral-900">{children}</h2>;
}

export function EmptyLine({ children }: { children: ReactNode }) {
  return <p className="text-sm text-neutral-400">{children}</p>;
}

/** 哲思内核模式徽标：linked 绿 / standalone 灰（原因由调用方附注）。 */
export function ModeBadge({ mode }: { mode: string }) {
  const { t } = useTranslation();
  const linked = mode === "linked";
  return (
    <span
      data-mode={mode}
      className={`inline-flex shrink-0 items-center rounded-full border px-2.5 py-0.5 text-xs ${
        linked
          ? "border-green-300 bg-green-50 text-green-800"
          : "border-neutral-300 bg-neutral-100 text-neutral-500"
      }`}
    >
      {t(linked ? "workbench.kernel.mode.linked" : "workbench.kernel.mode.standalone")}
    </span>
  );
}

/** 哲思来源标记：conflict/stance 注入后显示（hover 看卡 ID）。 */
export function ZhesiBadge({ meta }: { meta: ZhesiSource | null }) {
  const { t } = useTranslation();
  if (!meta) return null;
  const title = meta.cardIds.length
    ? `${t("workbench.zhesiBadge")} · ${meta.cardIds.join(", ")}`
    : t("workbench.zhesiBadge");
  return (
    <span
      title={title}
      className="ml-1.5 inline-flex shrink-0 items-center rounded-full border border-indigo-200 bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700"
    >
      {t("workbench.zhesiBadge")}
      {meta.cardIds.length ? <span className="ml-1 tabular-nums">×{meta.cardIds.length}</span> : null}
    </span>
  );
}

/** 通用「实体选择器」：Loadable 列表 → 下拉；降级/报错就地渲染。 */
export function Picker<T extends { id: string }>({
  label,
  state,
  selectedId,
  onSelect,
  labelOf,
}: {
  label: string;
  state: Loadable<T[]>;
  selectedId: string;
  onSelect: (id: string) => void;
  labelOf: (item: T) => string;
}) {
  const { t } = useTranslation();
  return (
    <label className="block text-sm">
      <span className="text-neutral-500">{label}</span>
      {state.status === "loading" ? (
        <Loading />
      ) : state.status === "unavailable" ? (
        <DegradeBox />
      ) : state.status === "error" ? (
        <ErrorBox message={state.message} code={state.code} />
      ) : state.status === "ready" ? (
        <select
          value={selectedId}
          onChange={(e) => onSelect(e.target.value)}
          className="mt-1 w-full rounded border border-neutral-300 bg-white px-2 py-1.5 text-sm focus:border-neutral-900 focus:outline-none"
        >
          <option value="">{t("workbench.pick")}</option>
          {state.data.map((item) => (
            <option key={item.id} value={item.id}>
              {labelOf(item)}
            </option>
          ))}
        </select>
      ) : (
        <select
          disabled
          className="mt-1 w-full rounded border border-neutral-200 bg-neutral-50 px-2 py-1.5 text-sm text-neutral-400"
        >
          <option value="">{t("workbench.pick")}</option>
        </select>
      )}
    </label>
  );
}

/** 主/次按钮的基础样式常量，面板里复用。 */
export const btnPrimary =
  "rounded-lg bg-neutral-900 px-4 py-2 text-sm text-white hover:bg-neutral-700 disabled:cursor-not-allowed disabled:opacity-40";
export const btnSecondary =
  "rounded-lg border border-neutral-300 bg-white px-3 py-1.5 text-sm text-neutral-700 hover:border-neutral-500 disabled:cursor-not-allowed disabled:opacity-40";
export const btnDanger =
  "rounded border border-red-200 bg-white px-2 py-1 text-xs text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-40";
export const inputText =
  "w-full rounded border border-neutral-300 bg-white px-2 py-1.5 text-sm focus:border-neutral-900 focus:outline-none";
