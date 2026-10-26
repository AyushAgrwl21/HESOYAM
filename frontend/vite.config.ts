import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const localApiOrigin = "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        target: localApiOrigin,
        changeOrigin: true,
      },
    },
  },
});
