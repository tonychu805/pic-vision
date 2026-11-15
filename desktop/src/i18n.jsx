import { Fragment, createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { t as translate } from "../electron/i18n/index.js";
import { currentLanguage, setCurrentLanguage, subscribeLanguage } from "./lib/language.js";

// Language for the whole window, as React state: choosing one redraws the
// screen in place (no reload, so a half-typed form or a running scan
// survives). The main process owns the saved choice -- it also needs the
// language for the tray and for errors it throws -- so this asks it on
// launch and tells it on every change.
const LanguageContext = createContext(null);

export function LanguageProvider({ children }) {
  const [lang, setLang] = useState(currentLanguage);
  // Until main has answered we only have the system-language guess; showing
  // that for a frame and then flipping would flash the wrong language at
  // anyone who chose the other one.
  const [ready, setReady] = useState(typeof window.languageAPI?.get !== "function");

  useEffect(() => subscribeLanguage(setLang), []);

  useEffect(() => {
    if (typeof window.languageAPI?.get !== "function") return undefined;
    let alive = true;
    window.languageAPI.get()
      .then((saved) => { if (alive) setCurrentLanguage(saved); })
      .catch(() => {})
      .finally(() => { if (alive) setReady(true); });
    return () => { alive = false; };
  }, []);

  const chooseLanguage = useCallback((next) => {
    setCurrentLanguage(next);
    window.languageAPI?.set(next).catch(() => {});
  }, []);

  const value = useMemo(
    () => ({
      lang,
      setLang: chooseLanguage,
      t: (key, vars) => translate(lang, key, vars),
      // For a sentence with a styled part: the values are React nodes, put
      // where the {placeholders} sit, in whatever order this language wants.
      rich: (key, nodes) => richText(translate(lang, key), nodes),
    }),
    [lang, chooseLanguage],
  );

  if (!ready) return null;
  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

function richText(template, nodes) {
  return template.split(/(\{\w+\})/).map((part, i) => {
    const name = /^\{(\w+)\}$/.exec(part)?.[1];
    return <Fragment key={i}>{name && name in nodes ? nodes[name] : part}</Fragment>;
  });
}

/** `const { t, rich, lang, setLang } = useI18n()`. */
export function useI18n() {
  const value = useContext(LanguageContext);
  // Outside the provider (a component rendered on its own in a test) it falls
  // back to the module's current language rather than throwing. The app always
  // renders inside the provider, so this only ever serves those renders.
  return value ?? standalone(currentLanguage());
}

const standaloneByLang = {};
function standalone(lang) {
  standaloneByLang[lang] ??= {
    lang,
    setLang: setCurrentLanguage,
    t: (key, vars) => translate(lang, key, vars),
    rich: (key, nodes) => richText(translate(lang, key), nodes),
  };
  return standaloneByLang[lang];
}
