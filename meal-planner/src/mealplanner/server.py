"""Meal planner MCP server: FastMCP tool definitions."""

from __future__ import annotations

import sqlite3
from typing import Literal

from mcp.server.fastmcp import FastMCP

from . import config, constraints, db, scrape, search, shopping, store, whatsapp

mcp = FastMCP(
    "mealplanner",
    instructions=(
        "Family meal-planning assistant. Typical weekly flow: check list_family and "
        "list_websites, search_recipes for each meal slot (pass the attendees so hard "
        "dietary constraints are enforced), create_meal_plan from the family's grid, "
        "assign_recipe_to_slot, generate_shopping_list, then send_whatsapp. "
        "Record liked/disliked feedback whenever the user comments on a recipe — "
        "it improves future search ranking."
    ),
)

settings = config.load()
_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = db.connect(settings.db_path)
    return _conn


# ------------------------------------------------------------------ family

@mcp.tool()
def upsert_family_member(
    name: str,
    age: int | None = None,
    hard_constraints: list[str] = [],
    likes: list[str] = [],
    dislikes: list[str] = [],
) -> dict:
    """Create a family member or fully replace their profile (age and all preferences).

    hard_constraints are non-negotiable and exclude recipes: diets ('vegan',
    'vegetarian', 'gluten free'), allergies ('nut allergy'), or literal bans
    ('no pumpkin'). likes/dislikes are soft preferences that only influence
    ranking and suggestions ('potatoes', 'spicy food'). Since this replaces the
    whole profile, pass the complete lists when updating an existing member.
    """
    return store.upsert_member(conn(), name, age, hard_constraints, likes, dislikes)


@mcp.tool()
def remove_family_member(name: str) -> dict:
    """Remove a family member and all their preferences and feedback."""
    return {"removed": store.remove_member(conn(), name)}


@mcp.tool()
def list_family() -> list[dict]:
    """List all family members with age, hard constraints, likes and dislikes."""
    return store.list_members(conn())


# ------------------------------------------------------------------ websites

@mcp.tool()
def add_website(domain: str) -> dict:
    """Add a website to the recipe search pool. Accepts a domain or full URL;
    it is normalized to a bare domain (e.g. 'seriouseats.com'). All recipe
    searches are restricted to this pool."""
    return {"websites": store.add_website(conn(), domain)}


@mcp.tool()
def remove_website(domain: str) -> dict:
    """Remove a website from the recipe search pool."""
    return {"websites": store.remove_website(conn(), domain)}


@mcp.tool()
def list_websites() -> list[str]:
    """List the websites recipe search is restricted to."""
    return store.list_websites(conn())


# ------------------------------------------------------------------ recipes

@mcp.tool()
def search_recipes(query: str, attendees: list[str] = [], max_results: int = 6) -> dict:
    """Search for recipes on the whitelisted websites only (via DuckDuckGo).

    Pass attendees (family member names) so their hard constraints are checked:
    recipes violating a constraint are NOT dropped but flagged in
    constraint_violations (member, constraint, matching ingredient) and ranked
    last — present them only if you mention the conflict. Ranking is also
    boosted by similarity to previously liked recipes; previously disliked
    recipe URLs are excluded entirely. Check 'skipped' and 'notes' for pages
    that failed to parse or search problems. Takes ~10-30s as pages are
    fetched and parsed live.
    """
    return search.search_recipes(
        conn(), query, attendees, max_results=max_results, max_fetch=settings.max_fetch
    )


@mcp.tool()
def get_recipe(url: str) -> dict:
    """Fetch, parse and cache a single recipe page by URL (works for any site,
    not just the whitelist — e.g. a recipe the user pasted). Returns full
    details including instructions."""
    cached = store.get_recipe_by_url(conn(), url, max_age_days=30)
    if cached:
        return cached
    html = scrape.fetch_url(url)
    recipe = scrape.parse_recipe(html, url)
    return store.upsert_recipe(conn(), recipe)


# ------------------------------------------------------------------ feedback

@mcp.tool()
def record_recipe_feedback(
    recipe_url: str,
    verdict: Literal["liked", "disliked"],
    member: str | None = None,
    notes: str | None = None,
) -> dict:
    """Record that the family (or one member, if given) liked or disliked a
    recipe. Use whenever the user comments on a recipe they tried — this
    tailors future search ranking (disliked URLs are never suggested again).
    A new verdict for the same recipe+member overwrites the old one."""
    c = conn()
    recipe = store.get_recipe_by_url(c, recipe_url)
    if recipe is None:
        html = scrape.fetch_url(recipe_url)
        recipe = store.upsert_recipe(c, scrape.parse_recipe(html, recipe_url))
    member_id = store.get_member(c, member)["id"] if member else None
    store.record_feedback(c, recipe["id"], verdict, member_id, notes)
    return {"recorded": True, "recipe": recipe["title"], "verdict": verdict,
            "member": member or "whole family"}


@mcp.tool()
def list_recipe_feedback(
    verdict: Literal["liked", "disliked"] | None = None,
    member: str | None = None,
) -> list[dict]:
    """List recorded recipe feedback, optionally filtered by verdict and/or
    member name. member=null in results means whole-family feedback."""
    c = conn()
    member_id = store.get_member(c, member)["id"] if member else None
    return store.list_feedback(c, verdict, member_id)


# ------------------------------------------------------------------ meal plans

@mcp.tool()
def create_meal_plan(name: str, slots: list[dict], start_date: str | None = None) -> dict:
    """Create a meal plan from a grid of slots. Each slot:
    {"day": "Monday", "meal": "lunch", "attendees": ["A", "B"]}.
    day can be a weekday name or ISO date; attendees are family member names
    (validated). Returns the plan with slot_ids used by assign_recipe_to_slot.
    Recipes are assigned separately after searching."""
    return store.create_plan(conn(), name, slots, start_date)


@mcp.tool()
def get_meal_plan(plan_id: int | None = None) -> dict:
    """Get a meal plan with its slots, attendees and assigned recipes.
    Defaults to the most recent plan; other plans are listed in other_plans."""
    return store.get_plan(conn(), plan_id)


@mcp.tool()
def update_plan_slot(
    plan_id: int,
    slot_id: int,
    attendees: list[str] | None = None,
    clear_recipe: bool = False,
) -> dict:
    """Update a plan slot: replace its attendee list and/or clear its assigned
    recipe (clear_recipe=true)."""
    store.update_slot(conn(), plan_id, slot_id, attendees, clear_recipe)
    return store.get_plan(conn(), plan_id)


@mcp.tool()
def assign_recipe_to_slot(plan_id: int, slot_id: int, recipe_url: str) -> dict:
    """Assign a recipe (by URL) to a plan slot. The recipe is fetched and
    cached automatically if not already known."""
    c = conn()
    recipe = store.get_recipe_by_url(c, recipe_url)
    if recipe is None:
        html = scrape.fetch_url(recipe_url)
        recipe = store.upsert_recipe(c, scrape.parse_recipe(html, recipe_url))
    store.assign_recipe(c, plan_id, slot_id, recipe["id"])
    return store.get_plan(c, plan_id)


# ------------------------------------------------------------------ output

@mcp.tool()
def generate_shopping_list(plan_id: int | None = None) -> dict:
    """Generate a shopping list for a meal plan (default: most recent).
    Ingredients are scaled by each slot's attendee count vs the recipe's
    servings and consolidated across recipes ('items'). Lines whose amounts
    couldn't be parsed are listed under 'unparsed' for manual checking.
    'text' is a ready-to-send formatted version — pass it to send_whatsapp."""
    return shopping.generate_shopping_list(conn(), plan_id)


@mcp.tool()
def send_whatsapp(message: str) -> dict:
    """Send a text message (e.g. the shopping list 'text') to the configured
    WhatsApp number via CallMeBot. Long messages are split into parts. If not
    configured, returns setup instructions instead of sending."""
    return whatsapp.send(message, settings.callmebot_phone, settings.callmebot_apikey)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
