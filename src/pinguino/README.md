# pinguino

A ground-up rebuild of the AMO Developer Hub as a Lit app, and the intended home for the new web foundations of the whole system. It runs alongside the classic Django/Jinja devhub (`src/olympia/devhub`) so the two can be compared in the same environment.

## Isolation

This is a self-contained frontend project. It does not use addons-server's root `package.json`, shared `vite.config.ts`, or any of the legacy jQuery/less pipeline, and there is no Django app in front of it - it's a pure SPA.

```
src/pinguino/
├── package.json / package-lock.json    # own deps: lit, @lit-labs/router, @mozilla/acorn-web-components
├── tsconfig.json                       # Lit-recommended TS (legacy decorators)
├── biome.json                          # lint + format (Biome, matches acorn)
├── vite.config.ts                      # base '/pinguino/', dev server on :5273
├── .npmrc                              # @mozilla scope -> GitHub Packages (token via env)
├── index.html                          # SPA shell
└── src/
    ├── main.ts                         # <pinguino-app> shell + client router
    ├── foundations/                    # shared foundations for the whole system
    │   └── acorn.ts                    # registers the acorn (moz-*) components + tokens
    └── devhub/                         # first product area
        ├── devhub-home.ts              # home page, built from moz-* components
        └── devhub-addon.ts             # detail page (:slug route param)
```

## Routing

Routing is client-side via [`@lit-labs/router`](https://www.npmjs.com/package/@lit-labs/router), configured in `main.ts`. The shell owns every path under `/pinguino/` and swaps views without a full page load; nginx only serves the shell. Add a page by adding a route in `main.ts`, no nginx change. (`urlpattern-polyfill` is imported for browsers without native `URLPattern`.)

The Router intercepts same-origin `<a>` clicks (across shadow DOM) and pushes history itself, so views navigate with plain `<a href="/pinguino/...">` links and the URL/back-forward stay correct.

## Component library (acorn)

UI is built from Mozilla's [`@mozilla/acorn-web-components`](https://github.com/mozilla/acorn-web-components) (the `moz-*` elements). `src/foundations/acorn.ts` imports the library (registering every `moz-*` element) and its design tokens; components are then used directly in templates.

While acorn is in alpha it's published to GitHub Packages, not the public npm registry. `.npmrc` maps the `@mozilla` scope there, and GitHub Packages requires a `read:packages` token even for public packages. Provide it as `NODE_AUTH_TOKEN`: put `NODE_AUTH_TOKEN=<token>` in the repo-root `.env` (gitignored), and `make up` passes it to the `pinguino` service so its `npm ci` can install acorn. (Only needed locally as pinguino isn't built into the production image; see below.)

Track the alpha with `npm add @mozilla/acorn-web-components@alpha`.

## Running locally

The usual root command brings it up with everything else:

```sh
make up
```

A dedicated `pinguino` docker-compose service (its own `node:24` image, deps in an isolated volume) runs `vite` on `:5273`; nginx proxies `/pinguino/` to it. Then:

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

The `_test_pinguino` GitHub Action runs all three on pull requests that touch `src/pinguino/`.

## Staging / production

Pinguino is local-only for now - it is deliberately not built into the production image, so it doesn't ship to staging or production. `make up` runs it locally via the `pinguino` dev service; the classic devhub is unaffected in every environment.

To ship it later:
1. Add a build stage to the repo `Dockerfile` that installs `@mozilla/acorn-web-components` (the GitHub Packages token must reach it as a build secret) and runs `npm run build`, then copy its `dist/` into the image (e.g. `site-static/pinguino/`).
2. Wire the token into the build: a `secret` on the `web` bake target (`docker-bake.hcl`) forwarding `NODE_AUTH_TOKEN`, supplied by whatever pipeline builds the production image.
3. Add a `/pinguino/` SPA-fallback route (`try_files $uri /pinguino/index.html`) to the deploy-infra nginx.
