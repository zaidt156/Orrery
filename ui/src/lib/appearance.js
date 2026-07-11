export const INTERFACE_MODES = Object.freeze(["classic", "concept"]);
export const COLOR_THEMES = Object.freeze(["simple", "futuristic", "winter", "summer", "observatory"]);

export const APPEARANCE_KEYS = Object.freeze({
  interfaceMode: "orrery-interface",
  colorTheme: "orrery-color-theme",
  legacyTheme: "orrery-theme",
});

export function normalizeInterface(value) {
  return INTERFACE_MODES.includes(value) ? value : "classic";
}

export function normalizeColorTheme(value) {
  return COLOR_THEMES.includes(value) ? value : "simple";
}

export function loadAppearance(storage) {
  const interfaceMode = normalizeInterface(storage.getItem(APPEARANCE_KEYS.interfaceMode));
  const savedColor = storage.getItem(APPEARANCE_KEYS.colorTheme);
  const legacyColor = savedColor == null ? storage.getItem(APPEARANCE_KEYS.legacyTheme) : null;
  const colorTheme = normalizeColorTheme(savedColor ?? legacyColor);

  if (legacyColor != null) {
    storage.setItem(APPEARANCE_KEYS.colorTheme, colorTheme);
    storage.removeItem(APPEARANCE_KEYS.legacyTheme);
  }

  return { interfaceMode, colorTheme };
}

export function applyAppearance(appearance, root) {
  root.dataset.interface = normalizeInterface(appearance.interfaceMode);
  root.dataset.colorTheme = normalizeColorTheme(appearance.colorTheme);
  return {
    interfaceMode: root.dataset.interface,
    colorTheme: root.dataset.colorTheme,
  };
}

export function saveInterface(value, storage) {
  const current = loadAppearance(storage);
  const interfaceMode = normalizeInterface(value);
  storage.setItem(APPEARANCE_KEYS.interfaceMode, interfaceMode);
  return { ...current, interfaceMode };
}

export function saveColorTheme(value, storage) {
  const current = loadAppearance(storage);
  const colorTheme = normalizeColorTheme(value);
  storage.setItem(APPEARANCE_KEYS.colorTheme, colorTheme);
  return { ...current, colorTheme };
}

export function initializeAppearance(storage = window.localStorage, root = document.documentElement) {
  return applyAppearance(loadAppearance(storage), root);
}
