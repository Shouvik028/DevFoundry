# DevFoundry Dashboard

Vite + React SPA. Talks to the FastAPI backend (`src/devfoundry/api`) over REST + WebSocket for live agent output, run history, and memory browsing.

Not required for daily use — the CLI is the primary interface. This is for visibility (Phase 3 per the spec) and eventual shareability.

## Scaffold (not yet run)

```bash
npm create vite@latest . -- --template react-ts
npm install
npm run dev
```

Add `vitest` for testing once there's real UI to test:

```bash
npm install -D vitest @testing-library/react
```
