// Theme preference for the desktop app.
//
// Deliberately simpler than the console's equivalent: there is no server
// and no SSR here, so the choice can live in localStorage and be applied
// by a plain inline script in index.html -- outside React entirely, before
// the bundle loads, so there is no wrong-theme flash and none of the
// "script rendered by a component never executes on the client" problem
// the console hit (see pic-vision-cloud-console/lib/theme.ts).
//
// 'system' is stored as the ABSENCE of the key, and writes no data-theme
// attribute. The prefers-color-scheme media query in index.css then
// decides -- and because Chromium follows the OS through Electron's
// nativeTheme, that keeps tracking a machine that switches at sunset
// without any code of ours listening for it.
// Also hardcoded in index.html's inline script, which runs before this
// module exists and so cannot import it. Change both together.
export const THEME_KEY = "pv-theme";
export const THEME_OPTIONS = [
  { value: "system", label: "System", icon: "ph-desktop" },
  { value: "light", label: "Light", icon: "ph-sun" },
  { value: "dark", label: "Dark", icon: "ph-moon" },
];

export function readTheme() {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    return stored === "light" || stored === "dark" ? stored : "system";
  } catch {
    // localStorage can throw outright when site data is blocked. A theme
    // toggle isn't worth taking the window down for.
    return "system";
  }
}

export function applyTheme(preference) {
  const root = document.documentElement;
  if (preference === "system") {
    delete root.dataset.theme;
  } else {
    root.dataset.theme = preference;
  }
  try {
    if (preference === "system") localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, preference);
  } catch {
    // Applied for this session, just not remembered.
  }
}
