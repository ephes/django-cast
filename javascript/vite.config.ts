import { resolve } from "path";
import { defineConfig } from "vite";
import type { UserConfig as VitestUserConfigInterface } from "vitest/config"

const vitestConfig: VitestUserConfigInterface = {
  test: {
    globals: true,
    environment: "jsdom",
  },
}

export default defineConfig({
  plugins: [],
  test: vitestConfig.test,
  root: resolve("./"),
  base: "/static/",
  server: {
    host: "0.0.0.0",
    port: 5173,
    open: false,
    watch: {
      usePolling: true,
      disableGlobbing: false,
    },
  },
  resolve: {
    extensions: [".js", ".json", ".ts"],
    alias: {
      "@": resolve("./src/"),
    },
  },
  build: {
    outDir: resolve("./dist"),
    assetsDir: "",
    manifest: true,
    emptyOutDir: true,
    target: "es2015",
    rollupOptions: {
      input: {
        main: resolve("./src/gallery/image-gallery-bs4.ts")
      },
      output: {
        chunkFileNames: undefined,
      },
    },
  },
})
