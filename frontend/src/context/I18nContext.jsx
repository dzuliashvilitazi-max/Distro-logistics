import { createContext, useContext, useState, useCallback } from "react";
import { translations } from "@/lib/i18n";

const I18nContext = createContext(null);
export const useI18n = () => useContext(I18nContext);

export function I18nProvider({ children }) {
  const [lang, setLangState] = useState(() => localStorage.getItem("distro_lang") || "en");

  const setLang = (l) => { localStorage.setItem("distro_lang", l); setLangState(l); };

  const t = useCallback((key) => {
    return translations[lang]?.[key] ?? translations.en[key] ?? key;
  }, [lang]);

  return <I18nContext.Provider value={{ lang, setLang, t }}>{children}</I18nContext.Provider>;
}
