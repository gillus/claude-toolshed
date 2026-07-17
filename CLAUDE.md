# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

Monorepo of self-contained, personal local MCP servers, each in its own directory with its own README, toolchain, and dependencies:

- `meal-planner/` — Python 3.10+ / FastMCP. Family meal planning: recipe search, constraint checking, meal plans, shopping lists, WhatsApp delivery.
- `schoolwork-tracker/` — TypeScript / `@modelcontextprotocol/sdk` (Node ≥ 20). Read-only bridge to Argo didUP, the Italian school register. Package name is `school-mcp`.
- `shared/` — placeholder for cross-server utilities; empty. Servers are polyglot, so anything factored here goes in per-language subfolders (`shared/python/`, `shared/ts/`).

## Commands

### meal-planner (uses uv)

```bash
cd meal-planner
uv sync                                     # install dependencies
uv run pytest                               # run tests (unit only, no network)
uv run pytest tests/test_store.py           # single test file
uv run pytest tests/test_store.py -k name   # single test
uv run mcp dev src/mealplanner/server.py    # MCP Inspector UI
```

### schoolwork-tracker

```bash
cd schoolwork-tracker
npm run setup          # install + build — NOT plain `npm install` (see below)
npm run build          # tsc
npm run dev            # run server from source via tsx
npm run check-login    # verify each configured account logs in (needs .env)
```

There is no test suite or linter here; `npm run build` (tsc, strict) is the check.

**`npm run setup` vs `npm install`:** the `portaleargo-api` dependency is installed from GitHub (no npm release) and its postinstall fails as a dependency. `setup` installs with `--ignore-scripts` then builds the library in place, tolerating a known harmless declaration-build error. Re-run `npm run setup` after any `npm install` that touches `node_modules/portaleargo-api`.

## Architecture

### meal-planner

Single package `src/mealplanner/`. `server.py` holds all MCP tool definitions (FastMCP) and is a thin layer over the other modules; keep logic out of it.

- `store.py` + `db.py` — SQLite persistence. Every `store.py` function takes an explicit `sqlite3.Connection` as its first argument; tests inject a tmp-path connection via the `conn` fixture in `tests/conftest.py`.
- `search.py` — DuckDuckGo `site:`-restricted search over the user-managed website pool, fetch, parse, then rank. Ranking demotes hard-constraint violations and disliked recipes and boosts similarity to liked ones. Liked recipes matching the query (`favorite_recipes`) join results straight from the DB, flagged `favorite: true`, without using a fetch slot. Scraped pages are cached in SQLite (30 days).
- `scrape.py` — recipe page → structured dict, via recipe-scrapers with a manual schema.org JSON-LD fallback.
- `constraints.py` — expands hard constraints (diet tags like `vegan`, or literal `no pumpkin`) into ingredient keyword lists; word-boundary matching produces violation records. Callers flag/demote violating recipes — never silently drop them.
- `shopping.py` — ingredient parsing and scaling by attendees vs recipe servings.
- `config.py` / `whatsapp.py` — env-var settings (`MEALPLANNER_DB`, `CALLMEBOT_*`, `MEALPLANNER_MAX_FETCH`) and CallMeBot sender. When CallMeBot vars are unset, `send_whatsapp` returns setup instructions instead of failing.

Tests are network-free: search/scrape tests use HTML fixtures under `tests/fixtures/`.

### schoolwork-tracker

- `src/config.ts` — loads `.env` from the project root. `ARGO_STUDENTS` is a comma-separated list of student names; each expands to `ARGO_<NAME>_SCHOOL_CODE/USERNAME/PASSWORD` variables.
- `src/argo.ts` — `StudentSession` wraps a `portaleargo-api` client per student: lazy login, TTL-based incremental re-sync (`ARGO_SYNC_TTL_MINUTES`, default 10) with in-flight dedup. `Sessions.get(name)` always returns a synced session. `ProfileSelectingClient` replaces the library's private `getLoginData` (which hardcodes the first child profile) so `ARGO_<NAME>_STUDENT_NAME` can bind each student to the right child on a shared parent account; after changing that mapping, delete `.argo-data/`. Also holds Argo date-parsing helpers (Argo mixes `YYYY-MM-DD`, `DD/MM/YYYY`, and datetime strings).
- `src/tools.ts` — all tool registrations. Every tool takes a `student` parameter (a zod enum built from configured names). A local `tool()` wrapper converts thrown errors into MCP error results; results are JSON text content. Tools filter/reshape the cached dashboard rather than hitting the API per call.
- `src/redact.ts` — opt-in name redaction (`ARGO_REDACT_NAMES=true`): tools pull `session.redactor` and pass every person-name field through `nameField()` (→ initials like "R.M."), free text through `text()` (known-name scrub), and emails through `email()` (dropped). New tool output fields must do the same.
- Session tokens and dashboard data persist under `.argo-data/` (gitignored), so restarts don't re-authenticate.
- The server is read-only by design — don't add tools that write to Argo.

## Windows deployment

Claude Desktop runs these servers natively on Windows from a synced copy at `C:\Users\gillu\claude-toolshed`. `scripts/sync-to-windows.sh` (modeled on trading_assistant's) builds schoolwork-tracker in WSL, rsyncs the tree (excluding `.git/`, `.venv/`, `.argo-data/`, caches — `.env` files ARE synced), and refreshes the meal-planner venv with the Windows `uv.exe`. schoolwork-tracker's `node_modules`/`dist` are synced as-is (pure-JS deps; its setup scripts don't run under cmd.exe). Re-run the script and restart Claude Desktop after changes.

schoolwork-tracker needs Node ≥ 20 at runtime (`portaleargo-api`'s undici requires the global `File`). Both the system Node in WSL and Windows are v18, so the MCP registrations point at standalone Node 24 runtimes: `~/.local/node-v24.18.0-linux-x64/bin/node` (WSL, `~/.claude.json`) and `C:\Users\gillu\AppData\Roaming\nvm\v24.18.0\node.exe` (Windows, `claude_desktop_config.json`) — installed via `nvm install` but never `nvm use`d, so the global Node 18 is untouched.

## Conventions

- stdout is reserved for the MCP stdio protocol in both servers — log to stderr only (`console.error` / never `print` in server code).
- Credentials live in `.env` files (gitignored) or env vars, never in code or the checked-in `.mcp.json`.
