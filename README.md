# claude-toolshed

Personal collection of local MCP servers for Claude.

## Servers

| Server | Stack | What it does |
|---|---|---|
| [`meal-planner/`](meal-planner/) | Python + FastMCP | Family meal planning: member dietary preferences, recipe search restricted to a website pool, liked/disliked learning, N-day meal plans, scaled shopping lists, WhatsApp delivery via CallMeBot |
| [`homework-tracker/`](homework-tracker/) | TypeScript + MCP SDK | Read-only bridge to Argo didUP (Italian school register): homework, grades, averages, lesson topics, notices, absences, timetable |
| `trading-assistant/` | — | Planned |
| [`shared/`](shared/) | — | Common utilities (empty for now) |

Each server is self-contained with its own README covering setup and
registration with Claude Code / Claude Desktop.

## Quick start

```bash
# meal-planner (Python, uses uv)
cd meal-planner && uv sync && uv run pytest

# homework-tracker (Node >= 20)
cd homework-tracker && npm run setup
```
