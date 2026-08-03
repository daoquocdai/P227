import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    allowedHosts: [
      ".trycloudflare.com",
      "silver-plants-know.loca.lt",
      "collaborative-tommy-stevens-ferrari.trycloudflare.com",
    ],
  },
});
