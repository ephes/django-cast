import { resolve } from "path";
import { defineConfig } from "vite";

export default defineConfig({
  root: resolve("./"),
  publicDir: false,
  build: {
    outDir: resolve("../src/cast/static/fluent_comments/js"),
    emptyOutDir: false,
    sourcemap: false,
    minify: false,
    target: "es2015",
    rollupOptions: {
      input: resolve("./src/comments/ajaxcomments.ts"),
      output: {
        format: "iife",
        entryFileNames: "ajaxcomments.js",
        inlineDynamicImports: true,
      },
    },
  },
});
