# Meal Planner MCP Server

A personal MCP server for family meal planning, designed to be driven by Claude
(Claude Code / Claude Desktop) for weekly meal recommendations.

**What it does**

- **Family registry** — members with age, hard dietary constraints (vegan,
  allergies, "no pumpkin"…) and soft likes/dislikes.
- **Recipe search restricted to your websites** — DuckDuckGo `site:` search over
  a user-managed domain pool, pages parsed into structured recipes
  (ingredients, servings, time) via recipe-scrapers / schema.org JSON-LD.
- **Constraint checking** — recipes violating an attendee's hard constraint are
  flagged (member + offending ingredient) and ranked last.
- **Taste learning** — record liked/disliked recipes; disliked URLs are never
  suggested again, and results similar to liked recipes are boosted.
- **Meal plans** — N-day plans from a grid of slots (`Monday lunch [A]`,
  `Monday dinner [A,B,C]`…), with recipes assigned per slot.
- **Shopping lists** — ingredients scaled by attendees vs recipe servings,
  consolidated across recipes, with a ready-to-send text version.
- **WhatsApp** — send the list (or anything) to your phone via CallMeBot.

## Setup

Requires [uv](https://docs.astral.sh/uv/). From this directory:

```bash
uv sync          # install dependencies
uv run pytest    # optional: run the test suite
```

## Registering with Claude Code

A project-level `.mcp.json` is included, so Claude Code sessions started in
this directory pick the server up automatically. To register it globally:

```bash
claude mcp add --scope user mealplanner \
  --env CALLMEBOT_PHONE=+39... --env CALLMEBOT_APIKEY=... \
  -- uv run --directory /home/gillus/claude-toolshed/meal-planner mealplanner-mcp
```

For Claude Desktop, add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mealplanner": {
      "command": "uv",
      "args": ["run", "--directory", "/home/gillus/claude-toolshed/meal-planner", "mealplanner-mcp"],
      "env": {
        "CALLMEBOT_PHONE": "+39...",
        "CALLMEBOT_APIKEY": "..."
      }
    }
  }
}
```

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `MEALPLANNER_DB` | `~/.local/share/mealplanner/mealplanner.db` | SQLite database path |
| `CALLMEBOT_PHONE` | unset | WhatsApp number, international format (`+39...`) |
| `CALLMEBOT_APIKEY` | unset | CallMeBot API key |
| `MEALPLANNER_MAX_FETCH` | `8` | Max recipe pages fetched per search |

### CallMeBot one-time setup (WhatsApp)

1. Add **+34 644 71 81 99** to your phone contacts.
2. Send it the WhatsApp message: `I allow callmebot to send me messages`.
3. You'll receive your personal API key; set the two env vars above.

If unset, the `send_whatsapp` tool returns these instructions instead of failing.

## Typical weekly session

> "Plan next week: Monday–Friday dinners for everyone, Tuesday lunch just for C.
> Something with potatoes at least once."

Claude will: check `list_family` / `list_websites` → `search_recipes` per slot
(passing attendees so constraints are enforced) → `create_meal_plan` →
`assign_recipe_to_slot` → `generate_shopping_list` → `send_whatsapp`.

First-time setup in a session: add your recipe sites
(`add_website("loveandlemons.com")`, …) and your family
(`upsert_family_member("B", 34, hard_constraints=["vegan"])`, …).
After cooking, tell Claude what everyone thought so it records feedback.

## Development

```bash
uv run pytest                                  # unit tests (no network)
uv run mcp dev src/mealplanner/server.py       # MCP Inspector UI
```

Layout: `src/mealplanner/` — `server.py` (16 MCP tools), `store.py`/`db.py`
(SQLite), `search.py` (DDG + ranking), `scrape.py` (recipe parsing),
`constraints.py` (diet rules), `shopping.py` (ingredient parsing/scaling),
`whatsapp.py` (CallMeBot).
