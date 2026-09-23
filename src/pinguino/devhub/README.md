# pinguino

A ground-up rebuild of the AMO Developer Hub as a Lit app, and the intended home for the new web foundations of the whole system. It runs alongside the classic Django/Jinja devhub (`src/olympia/devhub`) so the two can be compared in the same environment.

## Isolation

This is a self-contained frontend project. It does not use addons-server's root `package.json`, shared `vite.config.ts`, or any of the legacy jQuery/less pipeline, and there is no Django app in front of it - it's a pure SPA.

```
src/pinguino/                           # umbrella for pinguino projects
└── devhub/                             # this project (more sit alongside it)
    ├── package.json / package-lock.json  # own deps: lit, @lit-labs/router, @tanstack/lit-query, @mozilla/acorn-web-components
    ├── tsconfig.json                   # Lit-recommended TS (legacy decorators)
    ├── biome.json                      # lint + format (Biome, matches acorn)
    ├── vite.config.ts                  # base '/pinguino/', dev server on :5273
    ├── .npmrc                          # @mozilla scope -> GitHub Packages (token via env)
    ├── .env.example                    # AMO API config (VITE_AMO_*); copy to .env
    ├── index.html                      # SPA shell
    └── src/
        ├── main.ts                     # <pinguino-app> shell + client router
        ├── app.css                     # document-level styles
        ├── foundations/                # acorn registration + layout primitives
        │   ├── acorn.ts                # registers acorn (moz-*) components + tokens
        │   ├── layout/                 # layout primitives (app-grid/container/stack)
        │   └── illustrations/          # vendored design-kit SVGs
        ├── data/                       # data layer (see "Data and the AMO API")
        │   ├── http.ts                 # apiFetch: base URL, session auth, typed errors
        │   ├── api.ts                  # AMO endpoints + response mappers
        │   ├── query-client.ts         # shared TanStack Query cache
        │   ├── queries.ts              # query keys, lifetimes, mock-vs-API branch
        │   ├── mock.ts                 # built-in sample data
        │   ├── types.ts                # domain types
        │   ├── devtools.ts             # dev-only TanStack Query devtools
        │   └── index.ts                # public data API (barrel)
        ├── components/                 # UI: header, cards, updates feed
        └── pages/                      # route views: home, addon detail
```

## Routing

Routing is client-side via [`@lit-labs/router`](https://www.npmjs.com/package/@lit-labs/router), configured in `main.ts`. The shell owns every path under `/pinguino/` and swaps views without a full page load; nginx only serves the shell. Add a page by adding a route in `main.ts`, no nginx change. (`urlpattern-polyfill` is imported for browsers without native `URLPattern`.)

The Router intercepts same-origin `<a>` clicks (across shadow DOM) and pushes history itself, so views navigate with plain `<a href="/pinguino/...">` links and the URL/back-forward stay correct.

## Component library (acorn)

UI is built from Mozilla's [`@mozilla/acorn-web-components`](https://github.com/mozilla/acorn-web-components) (the `moz-*` elements). `src/foundations/acorn.ts` imports the library (registering every `moz-*` element) and its design tokens; components are then used directly in templates.

While acorn is in alpha it's published to GitHub Packages, not the public npm registry. `.npmrc` maps the `@mozilla` scope there, and GitHub Packages requires a `read:packages` token even for public packages. Provide it as `NODE_AUTH_TOKEN`: put `NODE_AUTH_TOKEN=<token>` in the repo-root `.env` (gitignored), and `make up` passes it to the `pinguino` service so its `npm ci` can install acorn. (Only needed locally as pinguino isn't built into the production image; see below.)

Track the alpha with `npm add @mozilla/acorn-web-components@alpha`.

## Data and the AMO API

Data access is a three-layer stack under `src/data/`, exposed through the `src/data/index.ts` barrel. Components attach query controllers and read reactive `{ data, isPending, isError }`; they never call `fetch` or track loading state themselves.

- **`http.ts`** - one `apiFetch()` owning the API base URL, the session auth header, JSON parsing, and a typed `ApiError` (carries the HTTP status, ready for a 401 -> login interceptor).
- **`api.ts`** - the AMO v5 endpoints (`fetchProfile`, `fetchAddons`, `fetchUpdates`) and the response-to-domain mappers.
- **`query-client.ts` + `queries.ts`** - a single [`@tanstack/lit-query`](https://tanstack.com/query/latest/docs/framework/lit/overview) cache plus the query definitions: stable keys, per-query lifetimes, and the mock-vs-API branch. Caching, dedup, and invalidation live here, so shared long-lived data (e.g. the signed-in developer profile) is fetched once and reused across pages instead of re-fetched on every mount.

With no API configured the app runs on the built-in mock data in `mock.ts`. To point it at a real AMO instance, copy `.env.example` to `.env` (gitignored, project-level - separate from the repo-root `.env` that carries `NODE_AUTH_TOKEN`) and set:

- `VITE_AMO_SESSION_ID` - a logged-in AMO session id, sent as `Authorization: Session <id>`.
- `VITE_AMO_AUTHOR` - the author (account id or username) whose add-ons to list.
- `VITE_AMO_API_BASE` - optional; defaults to same-origin `/api/v5` (local olympia via nginx).

With both a session and an author set, queries hit the API and a failed request surfaces as an error state rather than silently falling back to mock data. There's no FxA login flow yet - the session id is supplied by hand. Vite restarts when `.env` changes, so reload after editing it.

The [TanStack Query devtools](https://tanstack.com/query/latest/docs/framework/react/devtools) (`src/data/devtools.ts`) mount a floating panel for inspecting cache state, staleness, and refetches. They're loaded via a dynamic import behind `import.meta.env.DEV` in `main.ts`, so they run locally and are dropped from production builds.

## Running locally

The usual root command brings it up with everything else:

```sh
make up
```

A dedicated `pinguino` docker-compose service (its own `node:24-slim` image, deps in an isolated volume) runs `vite` on `:5273`; nginx proxies `/pinguino/` to it. Then:

- Pinguino (new): http://olympia.test/pinguino/
- Classic devhub (existing): http://olympia.test/developers/

Both run at once. Editing files under `src/pinguino/src/` hot-reloads the page (HMR is proxied through nginx). To work directly against the service:

```sh
docker compose exec pinguino npm run typecheck
docker compose exec pinguino npm run build
docker compose logs -f pinguino
docker compose up -d --force-recreate pinguino
```

Making changes to configuration files like `package.json`, `vite.config.ts` or `tsconfig.json` requires restarting the development server to take effect.

## Checks

- `npm run lint` runs Biome (lint + format check), configured in `biome.json` to match acorn's setup. `npm run format` applies its fixes.
- `npm run typecheck` and `npm run build` cover types and the production bundle.

Dependencies install into the container's isolated volume, so run these checks inside the service (`docker compose exec pinguino ...`). Add packages the same way (`docker compose exec pinguino npm add <pkg>`) so the container volume and the committed lockfile stay in sync; the host's `node_modules` is not used.

The `_test_pinguino` GitHub Action runs all three on pull requests that touch `src/pinguino/`.

## Staging / production

Pinguino is local-only for now - it is deliberately not built into the production image, so it doesn't ship to staging or production. `make up` runs it locally via the `pinguino` dev service; the classic devhub is unaffected in every environment.

To ship it later:
1. Add a build stage to the repo `Dockerfile` that installs `@mozilla/acorn-web-components` (the GitHub Packages token must reach it as a build secret) and runs `npm run build`, then copy its `dist/` into the image (e.g. `site-static/pinguino/`).
2. Wire the token into the build: a `secret` on the `web` bake target (`docker-bake.hcl`) forwarding `NODE_AUTH_TOKEN`, supplied by whatever pipeline builds the production image.
3. Add a `/pinguino/` SPA-fallback route (`try_files $uri /pinguino/index.html`) to the deploy-infra nginx.
