import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Where both proxies below forward `/api`. Overridable because the port on the
// far end is uvicorn's `--port` flag and nothing kept the two in step: someone
// whose 8000 was already taken — a common enough default — got a dev server that
// started cleanly, a page that rendered, and a bare 502 on every request, with
// the only clue in this file. That is the same silent failure the proxy was
// introduced to remove, surviving on the other side of the hop.
const API_TARGET = process.env.VITE_API_TARGET || 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],

  // Why the proxy: the browser then sees same-origin `/api/...` requests, so the
  // dev server never triggers CORS at all. Before this, api.js pointed straight at
  // http://localhost:8000 and backend/main.py allowed exactly two origins — if 5173
  // was taken, Vite moved to 5174 and every request was silently CORS-blocked. The
  // page rendered normally with no data and no error, which is close to unsearchable
  // for someone running this for the first time.
  //
  // strictPort turns that same collision into a loud startup failure instead: the
  // launchers open http://localhost:5173 on a fixed timer, so a dev server that
  // quietly moved elsewhere would leave the browser pointed at the wrong thing.
  //
  // The AI endpoints stream NDJSON; Vite's proxy pipes responses rather than
  // buffering them, so progressive delivery survives the hop.
  //
  // The target is 127.0.0.1 rather than localhost to pin it to IPv4, matching the
  // address uvicorn binds by default. Both resolve here; the literal just removes
  // any dependence on how a given host orders IPv6 and IPv4 for `localhost`.
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': API_TARGET },
  },

  // `npm run preview` serves the production build and needs the same hop.
  // Serving dist/ from anywhere else means bringing your own reverse proxy.
  preview: {
    proxy: { '/api': API_TARGET },
  },
})
