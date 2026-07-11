import { createContext, useContext, useMemo, useState } from "react";
import {
  applyAppearance,
  loadAppearance,
  saveColorTheme,
  saveInterface,
} from "../lib/appearance.js";

const AppearanceContext = createContext(null);

export function AppearanceProvider({ children }) {
  const [appearance, setAppearance] = useState(() => loadAppearance(window.localStorage));

  const value = useMemo(() => ({
    ...appearance,
    setInterfaceMode(next) {
      const saved = saveInterface(next, window.localStorage);
      applyAppearance(saved, document.documentElement);
      setAppearance(saved);
    },
    setColorTheme(next) {
      const saved = saveColorTheme(next, window.localStorage);
      applyAppearance(saved, document.documentElement);
      setAppearance(saved);
    },
  }), [appearance]);

  return <AppearanceContext.Provider value={value}>{children}</AppearanceContext.Provider>;
}

export function useAppearance() {
  const value = useContext(AppearanceContext);
  if (!value) throw new Error("useAppearance must be used inside AppearanceProvider");
  return value;
}
