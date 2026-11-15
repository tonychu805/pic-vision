import { LANGS, LANG_NAMES } from "../../electron/i18n/index.js";
import { useI18n } from "../i18n.jsx";

// Two buttons, each named in its own language ("English", "繁體中文") so the
// one you can't read is still findable. Same look as ThemeToggle: a segmented
// control, one click, no menu.
export default function LanguageSwitch({ compact = false }) {
  const { lang, setLang, t } = useI18n();
  return (
    <div
      role="radiogroup"
      aria-label={t("language.label")}
      style={{
        display: "flex",
        gap: 2,
        padding: 2,
        borderRadius: "var(--radius-md)",
        background: "color-mix(in srgb, var(--color-text) 4%, transparent)",
      }}
    >
      {LANGS.map((code) => {
        const active = lang === code;
        return (
          <button
            key={code}
            type="button"
            role="radio"
            aria-checked={active}
            lang={code}
            onClick={() => setLang(code)}
            style={{
              flex: 1,
              padding: compact ? "4px 0" : "5px 12px",
              border: 0,
              borderRadius: "calc(var(--radius-md) - 2px)",
              cursor: "pointer",
              font: "inherit",
              fontSize: "var(--fs-fine)",
              whiteSpace: "nowrap",
              background: active ? "var(--color-surface)" : "transparent",
              color: active ? "var(--color-accent)" : "var(--text-3)",
              boxShadow: active ? "var(--shadow-sm)" : "none",
            }}
          >
            {LANG_NAMES[code]}
          </button>
        );
      })}
    </div>
  );
}
