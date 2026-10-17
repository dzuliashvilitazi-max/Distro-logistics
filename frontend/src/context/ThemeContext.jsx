import { createContext, useContext, useEffect, useState } from "react";

const ThemeContext = createContext(null);
export const useTheme = () => useContext(ThemeContext);

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(() => localStorage.getItem("distro_theme") || "dark");

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "dark") root.classList.add("dark");
    else root.classList.remove("dark");
    localStorage.setItem("distro_theme", theme);
  }, [theme]);

  const toggle = () => setTheme((t) => (t === "dark" ? "light" : "dark"));

  return <ThemeContext.Provider value={{ theme, toggle }}>{children}</ThemeContext.Provider>;
}
