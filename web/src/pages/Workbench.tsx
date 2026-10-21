/** 工作台：剧本 / 哲思 / 底料 三 tab（juchuang-script-studio web 任务）。 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import ScreenplayPanel from "./workbench/ScreenplayPanel";
import KernelPanel from "./workbench/KernelPanel";
import PipelinePanel from "./workbench/PipelinePanel";

type Tab = "screenplay" | "kernel" | "pipeline";
const TABS: readonly Tab[] = ["screenplay", "kernel", "pipeline"];

export default function Workbench() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("screenplay");

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <h1 className="text-2xl font-serif">{t("workbench.title")}</h1>
      <p className="mt-1 text-sm text-neutral-500">{t("workbench.subtitle")}</p>

      <div className="mt-6 flex gap-1 border-b border-neutral-200" role="tablist">
        {TABS.map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm transition-colors ${
              tab === k
                ? "border-neutral-900 font-medium text-neutral-900"
                : "border-transparent text-neutral-500 hover:text-neutral-900"
            }`}
          >
            {t(`workbench.tabs.${k}`)}
          </button>
        ))}
      </div>

      <div className="mt-8">
        {tab === "screenplay" ? <ScreenplayPanel /> : null}
        {tab === "kernel" ? <KernelPanel /> : null}
        {tab === "pipeline" ? <PipelinePanel /> : null}
      </div>
    </main>
  );
}
