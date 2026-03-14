import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

const backendHost = process.env.B2T_BACKEND_HOST || "127.0.0.1";
const backendPort = process.env.B2T_BACKEND_PORT || "8000";

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 6010,
    proxy: {
      "/api": {
        target: `http://${backendHost}:${backendPort}`,
        changeOrigin: true,
      },
    },
  },
});
