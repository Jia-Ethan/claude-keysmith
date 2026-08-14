import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

// Tauri 2 标准配置：固定端口，strictPort，清空输出目录。
// 构建信息（版本/渠道/commit）由 scripts/generate-build-info.mjs 生成到
// src/lib/build-info.generated.js，不再通过 define 注入。
export default defineConfig({
  clearScreen: false,
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 1420,
    strictPort: true,
    watch: {
      ignored: ["**/src-tauri/**"],
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        // Split the heaviest vendor groups to cap individual chunk size and
        // give stable libraries independent cache granularity.
        manualChunks: {
          react: ["react", "react-dom", "react-dom/client"],
          radix: [
            "@radix-ui/react-alert-dialog",
            "@radix-ui/react-collapsible",
            "@radix-ui/react-dialog",
            "@radix-ui/react-label",
            "@radix-ui/react-select",
            "@radix-ui/react-slot",
            "@radix-ui/react-switch",
            "@radix-ui/react-tooltip",
          ],
          motion: ["motion"],
          i18n: ["i18next", "react-i18next"],
        },
      },
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.{js,jsx}"],
  },
});
