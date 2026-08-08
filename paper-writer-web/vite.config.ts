import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  // 后端地址从 .env 读取（VITE_API_URL），未配置时默认本地 8000
  const apiTarget = env.VITE_API_URL || "http://localhost:8000";

  return {
    plugins: [react(), tailwindcss()],
    server: {
      // 监听所有网卡：localhost / 127.0.0.1 / 局域网 IP 均可访问
      host: true,
      port: 5173,
      strictPort: true,
      proxy: {
        // 开发模式把 /api 代理到 paper-writer-api，避免跨域问题
        "/api": {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
  };
});
