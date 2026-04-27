# Repository Guidelines

## Project Structure & Module Organization
`nanobot/` contains the Python runtime: CLI, agent loop, providers, channels, security, session state, and built-in skills. `tests/` mirrors that layout (`tests/providers`, `tests/channels`, `tests/cli`, etc.) and should grow alongside production modules. Docs live in `docs/`. Prompt and workspace templates are under `nanobot/templates/`. The browser client lives in `webui/` (`src/components`, `src/hooks`, `src/lib`, `src/tests`), and its production build is emitted to `nanobot/web/dist/`. The WhatsApp bridge is a separate TypeScript project in `bridge/src/`.

## Build, Test, and Development Commands
Install the Python app with dev tools from the repo root:
```bash
pip install -e ".[dev]"
pytest
ruff check .
ruff format .
```
If you use `uv`, make sure commands run with a `uv`-managed Python `3.11+` interpreter. Having `uv` installed is not enough if your shell still resolves to an older system Python such as `3.9`. A reliable flow is:
```bash
uv run --python 3.12 --extra dev pytest
uv run --python 3.12 --extra dev ruff check .
uv run --python 3.12 --extra dev ruff format .
```
Use `pytest --cov=nanobot` when touching core runtime paths. For the WebUI:
```bash
cd webui
bun install
bun run dev
bun run build
bun run test
bun run lint
```
For the WhatsApp bridge:
```bash
cd bridge
npm install
npm run build
npm run dev
```

## Coding Style & Naming Conventions
Target Python 3.11+, 4-space indentation, and Ruff defaults from `pyproject.toml` (line length 100; rules `E,F,I,N,W`). Keep modules focused and prefer small, readable patches over framework-heavy abstraction. Use `snake_case` for Python functions/modules, `PascalCase` for React components, and colocate tests with the feature area they cover. Follow existing Markdown/template wording patterns in `nanobot/templates/` and `nanobot/skills/`.

## Testing Guidelines
Python tests use `pytest` with `pytest-asyncio`; add async coverage for provider, channel, and tool behavior when relevant. Name files `test_<feature>.py` and mirror package paths. WebUI tests use Vitest and Testing Library from `webui/src/tests`; keep test names behavior-oriented. The bridge currently has no dedicated test script, so validate it with a clean TypeScript build before opening a PR.

## Commit & Pull Request Guidelines
Recent history follows Conventional Commit prefixes such as `feat:`, `fix:`, `docs:`, `chore:` and scoped forms like `feat(read_file): ...`. Keep subjects imperative and specific. Target `nightly` for new features/refactors and `main` for low-risk fixes or docs, following `CONTRIBUTING.md`. PRs should explain user-visible impact, list verification commands, link related issues, and include screenshots for `webui/` changes.

## Security & Configuration Tips
Never commit real API keys, chat credentials, or local `~/.nanobot/config.json` values. Review `SECURITY.md` before changing auth, sandboxing, or network-facing behavior.
