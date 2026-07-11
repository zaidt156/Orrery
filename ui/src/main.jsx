import React from "react";
import { createRoot } from "react-dom/client";

// self-hosted fonts (bundled, offline, no CDN — local-first)
import "@fontsource-variable/bricolage-grotesque";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";

import "highlight.js/styles/github-dark.css";  // syntax highlighting theme for code blocks

import App from "./App.jsx";
import { AppearanceProvider } from "./components/AppearanceProvider.jsx";
import { initializeAppearance } from "./lib/appearance.js";
import "./styles.css";
import "./appearance.css";

// Apply both appearance axes before first paint. Interface geometry and color palette are stored
// independently, so changing Futuristic can never switch the user's Classic/Concept layout.
initializeAppearance();

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <AppearanceProvider>
      <App />
    </AppearanceProvider>
  </React.StrictMode>
);
