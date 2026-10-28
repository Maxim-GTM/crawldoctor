/// <reference types="vitest/config" />
import path from "path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// The backend (or the full image's nginx) on :8000 serves the API, the tracker and /health.
const backend = process.env.CRAWLDOCTOR_DEV_BACKEND ?? "http://localhost:8000"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "./src") } },
  server: { proxy: { "/api": backend, "/track": backend, "/health": backend } },
  // The Dockerfile copies frontend/build into the image, as it did with Create React App.
  build: { outDir: "build" },
  test: { environment: "jsdom", setupFiles: ["./src/test/setup.ts"], css: false },
})
