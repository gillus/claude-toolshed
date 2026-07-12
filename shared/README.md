# shared

Common utilities for the MCP servers in this repo (auth helpers, config
loading, notification senders, …).

Empty for now — factor code out here when at least two servers need it.
Note the servers are polyglot (Python and TypeScript), so shared code should
live in per-language subfolders, e.g. `shared/python/`, `shared/ts/`.
