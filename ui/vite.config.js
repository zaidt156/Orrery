import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build to ui/dist, which FastAPI serves in non-dev mode. Relative base so the
// bundled assets load no matter what path the desktop window points at.
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: { port: 5173, strictPort: true },
  build: { outDir: "dist", emptyOutDir: true },
});
