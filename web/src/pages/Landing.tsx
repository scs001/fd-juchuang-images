import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

/** 剧本页显影——场灯亮起，页面唯一的动效时刻：场景行与台词逐行显影。 */
function ScriptCard() {
  const { t } = useTranslation();
  return (
    <figure className="rounded-xl border border-moon/15 bg-stage-deep/60 p-6">
      <figcaption className="cue-line font-display text-xs tracking-[0.2em] text-gold">{t("landing.visual.scene")}</figcaption>
      <div className="mt-4 space-y-3.5">
        <p className="cue-line cue-line-1 font-display text-sm text-moon/50">{t("landing.visual.direction")}</p>
        <p className="cue-line cue-line-2 text-[15px] leading-relaxed text-moon/90">
          <span className="mr-3 font-display text-gold/90">{t("landing.visual.speaker1")}</span>
          {t("landing.visual.line1")}
        </p>
        <p className="cue-line cue-line-3 text-[15px] leading-relaxed text-moon/90">
          <span className="mr-3 font-display text-gold/90">{t("landing.visual.speaker2")}</span>
          {t("landing.visual.line2")}
        </p>
        <p className="cue-line cue-line-4 text-xs leading-relaxed text-moon/40">{t("landing.visual.note")}</p>
      </div>
    </figure>
  );
}

function Band({ index, name, title, body, detail }: { index: number; name: string; title: string; body: string; detail: string }) {
  return (
    <section className={`border-t border-line ${index % 2 === 1 ? "bg-mist" : "bg-paper"}`}>
      <div className="mx-auto grid max-w-5xl gap-6 px-6 py-14 md:grid-cols-[10rem_1fr] md:gap-12 md:py-16">
        <div className="font-display text-2xl text-ink/40 md:text-right">{name}</div>
        <div className="max-w-2xl">
          <h2 className="font-display text-2xl leading-snug text-ink md:text-[1.7rem]">{title}</h2>
          <p className="mt-4 leading-loose text-ink-soft">{body}</p>
          <p className="mt-3 text-sm leading-relaxed text-ink-soft/90">{detail}</p>
        </div>
      </div>
    </section>
  );
}

export default function Landing() {
  const { t } = useTranslation();
  const bands = (["screenplay", "kernel", "pipeline"] as const).map((k) => ({
    name: t(`landing.loops.${k}.name`),
    title: t(`landing.loops.${k}.title`),
    body: t(`landing.loops.${k}.body`),
    detail: t(`landing.loops.${k}.detail`),
  }));
  return (
    <main className="bg-paper">
      {/* Hero——场灯暗下的舞台 */}
      <section className="bg-stage text-moon">
        <div className="mx-auto grid max-w-6xl items-center gap-12 px-6 py-20 lg:grid-cols-12 lg:py-28">
          <div className="lg:col-span-7">
            <h1 className="hero-rise font-display text-5xl leading-tight tracking-wide text-white md:text-6xl">
              {t("landing.hero.statement1")}
            </h1>
            <p className="hero-rise hero-rise-1 mt-5 font-display text-2xl leading-snug text-moon/85 md:text-3xl">
              {t("landing.hero.statement2")}
            </p>
            <p className="hero-rise hero-rise-2 mt-7 max-w-xl leading-loose text-moon/70">
              {t("landing.hero.lede")}
            </p>
            <div className="hero-rise hero-rise-3 mt-10 flex flex-wrap items-center gap-4">
              <Link to="/workbench" className="rounded-md bg-gold px-6 py-3 text-sm font-medium text-stage-deep transition-colors hover:bg-gold/85">
                {t("landing.hero.cta")}
              </Link>
              <a href="#loops" className="rounded-md border border-moon/30 px-6 py-3 text-sm text-moon transition-colors hover:border-moon/70">
                {t("landing.hero.ctaSecondary")}
              </a>
            </div>
          </div>
          <div className="lg:col-span-5">
            <ScriptCard />
          </div>
        </div>
      </section>

      <div id="loops" className="scroll-mt-16">
        {bands.map((b, i) => (
          <Band key={b.name} index={i} {...b} />
        ))}
      </div>

      {/* 哲思内核——产品真话 */}
      <section className="border-t border-line bg-stage-deep text-moon">
        <div className="mx-auto max-w-3xl px-6 py-16 text-center">
          <h2 className="font-display text-2xl leading-snug text-white md:text-3xl">{t("landing.truth.title")}</h2>
          <p className="mx-auto mt-5 max-w-xl leading-loose text-moon/70">{t("landing.truth.body")}</p>
          <p className="mx-auto mt-4 max-w-xl text-sm leading-relaxed text-moon/45">{t("landing.truth.sub")}</p>
        </div>
      </section>

      {/* CTA */}
      <section className="border-t border-line bg-paper">
        <div className="mx-auto max-w-3xl px-6 py-20 text-center">
          <h2 className="font-display text-3xl leading-snug text-ink">{t("landing.cta.title")}</h2>
          <p className="mt-4 leading-loose text-ink-soft">{t("landing.cta.body")}</p>
          <Link to="/workbench" className="mt-8 inline-block rounded-md bg-stage px-8 py-3.5 text-sm font-medium text-moon transition-colors hover:bg-stage-deep">
            {t("landing.hero.cta")}
          </Link>
          <p className="mt-6 text-xs text-ink-soft/70">{t("landing.cta.family")}</p>
        </div>
      </section>
    </main>
  );
}
