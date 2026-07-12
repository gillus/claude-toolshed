"""Fetch recipe pages and parse them into structured dicts.

Parse order: recipe-scrapers (site-specific + schema.org wild mode), then a
manual JSON-LD fallback for pages recipe-scrapers can't handle.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from recipe_scrapers import scrape_html

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class ScrapeError(Exception):
    pass


def fetch_url(url: str, timeout: float = 10.0) -> str:
    try:
        resp = httpx.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en;q=0.9, *;q=0.5"},
        )
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPStatusError as e:
        raise ScrapeError(f"HTTP {e.response.status_code}") from e
    except httpx.HTTPError as e:
        raise ScrapeError(f"fetch failed: {type(e).__name__}") from e


def parse_recipe(html: str, url: str) -> dict:
    """Return {url, title, site, servings, yields_raw, total_time_min, ingredients, instructions}.

    Raises ScrapeError if no recipe can be extracted.
    """
    site = urlparse(url).netloc.removeprefix("www.")
    try:
        recipe = _parse_with_recipe_scrapers(html, url)
    except Exception:
        recipe = _parse_json_ld(html)
        if recipe is None:
            raise ScrapeError("no recipe data found (not a recipe page?)")
    if not recipe.get("ingredients"):
        raise ScrapeError("recipe has no ingredients")
    recipe["url"] = url
    recipe["site"] = site
    recipe["servings"] = _servings_from_yield(recipe.get("yields_raw"))
    return recipe


def _parse_with_recipe_scrapers(html: str, url: str) -> dict:
    s = scrape_html(html, org_url=url, supported_only=False)
    ingredients = s.ingredients()
    if not ingredients:
        raise ScrapeError("no ingredients")

    def safe(getter):
        try:
            return getter()
        except Exception:
            return None

    return {
        "title": safe(s.title),
        "yields_raw": safe(s.yields),
        "total_time_min": safe(s.total_time),
        "ingredients": ingredients,
        "instructions": safe(s.instructions),
    }


def _parse_json_ld(html: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        node = _find_recipe_node(data)
        if node:
            return _recipe_from_node(node)
    return None


def _find_recipe_node(data) -> dict | None:
    if isinstance(data, list):
        for item in data:
            found = _find_recipe_node(item)
            if found:
                return found
        return None
    if not isinstance(data, dict):
        return None
    types = data.get("@type", "")
    if isinstance(types, str):
        types = [types]
    if "Recipe" in types:
        return data
    return _find_recipe_node(data.get("@graph", []))


def _recipe_from_node(node: dict) -> dict:
    ingredients = node.get("recipeIngredient") or []
    if isinstance(ingredients, str):
        ingredients = [ingredients]

    instructions = node.get("recipeInstructions")
    if isinstance(instructions, list):
        steps = []
        for step in instructions:
            if isinstance(step, dict):
                if step.get("@type") == "HowToSection":
                    steps.extend(
                        s.get("text", "") for s in step.get("itemListElement", [])
                        if isinstance(s, dict)
                    )
                else:
                    steps.append(step.get("text", ""))
            elif isinstance(step, str):
                steps.append(step)
        instructions = "\n".join(s for s in steps if s)

    yields_raw = node.get("recipeYield")
    if isinstance(yields_raw, list):
        yields_raw = yields_raw[0] if yields_raw else None
    if yields_raw is not None:
        yields_raw = str(yields_raw)

    return {
        "title": node.get("name"),
        "yields_raw": yields_raw,
        "total_time_min": _iso_duration_to_minutes(node.get("totalTime")),
        "ingredients": [str(i).strip() for i in ingredients if str(i).strip()],
        "instructions": instructions if isinstance(instructions, str) else None,
    }


def _iso_duration_to_minutes(value) -> int | None:
    if not value or not isinstance(value, str):
        return None
    m = re.fullmatch(
        r"P(?:(?P<d>\d+)D)?T?(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?", value.strip()
    )
    if not m or not any(m.groupdict().values()):
        return None
    d, h, mi, s = (int(m.group(g) or 0) for g in ("d", "h", "m", "s"))
    return d * 24 * 60 + h * 60 + mi + round(s / 60)


def _servings_from_yield(yields_raw) -> int | None:
    """'4 servings' / 'Serves 6' / '12' -> int, else None."""
    if yields_raw is None:
        return None
    if isinstance(yields_raw, (int, float)):
        return int(yields_raw) or None
    m = re.search(r"\d+", str(yields_raw))
    return int(m.group()) if m else None
