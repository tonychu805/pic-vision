import { useState } from "react";
import { THEME_OPTIONS, applyTheme, readTheme } from "../lib/theme.js";
import { useI18n } from "../i18n.jsx";

// Three icon buttons in the sidebar footer rather than a row in a settings
// page: this app deliberately has no general Settings tab (Scan options
// lives under Cameras, next to the button it configures), and adding a
// whole nav item for one preference is exactly the thing that got Scan
// settings demoted. It's compact enough for the 196px sidebar and always
// one click away.
//
// Reads localStorage during the initial state calculation rather than in
// an effect: unlike the console this is a plain client render with no
// hydration to mismatch, so there's nothing to defer.
export default function ThemeToggle({ collapsed }) {
  const { t } = useI18n();
  const [preference, setPreference] = useState(readTheme);

  const choose = (value) => {
    setPreference(value);
    applyTheme(value);
  };

  return (
    <div
      role="radiogroup"
      aria-label={t("theme.label")}
      style={{
        display: "flex",
        gap: 2,
        padding: 2,
        borderRadius: "var(--radius-md)",
        background: "color-mix(in srgb, var(--color-text) 4%, transparent)",
        justifyContent: collapsed ? "center" : "stretch",
      }}
    >
      {THEME_OPTIONS.map((option) => {
        const active = preference === option.value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            title={t("theme.title", { name: t(option.labelKey) })}
            onClick={() => choose(option.value)}
            style={{
              flex: 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 5,
              padding: "5px 0",
              border: 0,
              borderRadius: "calc(var(--radius-md) - 2px)",
              cursor: "pointer",
              font: "inherit",
              fontSize: "var(--fs-fine)",
              background: active ? "var(--color-surface)" : "transparent",
              color: active ? "var(--color-accent)" : "var(--text-3)",
              boxShadow: active ? "var(--shadow-sm)" : "none",
            }}
          >
            <i className={`ph ${option.icon}`} style={{ fontSize: 14 }} />
          </button>
        );
      })}
    </div>
  );
}
