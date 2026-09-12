import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// server.host=true de nghe tren 0.0.0.0 trong container (T-0.10);
// nginx proxy vao day qua ten service `web` tren network `internal`.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    port: 5173,
    strictPort: true,
  },
});
