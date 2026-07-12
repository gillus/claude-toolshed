"""Shopping list generation: parse ingredient lines, scale by attendees,
consolidate across recipes."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from . import store

DEFAULT_SERVINGS = 4

# unit -> (dimension, factor to base unit). Base units: g (mass), ml (volume), count.
UNITS: dict[str, tuple[str, float]] = {
    "g": ("mass", 1), "gram": ("mass", 1), "grams": ("mass", 1),
    "kg": ("mass", 1000), "kilogram": ("mass", 1000), "kilograms": ("mass", 1000),
    "oz": ("mass", 28.35), "ounce": ("mass", 28.35), "ounces": ("mass", 28.35),
    "lb": ("mass", 453.6), "lbs": ("mass", 453.6), "pound": ("mass", 453.6), "pounds": ("mass", 453.6),
    "ml": ("volume", 1), "milliliter": ("volume", 1), "milliliters": ("volume", 1),
    "cl": ("volume", 10), "dl": ("volume", 100),
    "l": ("volume", 1000), "liter": ("volume", 1000), "liters": ("volume", 1000),
    "litre": ("volume", 1000), "litres": ("volume", 1000),
    "cup": ("volume", 240), "cups": ("volume", 240),
    "tbsp": ("volume", 15), "tablespoon": ("volume", 15), "tablespoons": ("volume", 15),
    "tsp": ("volume", 5), "teaspoon": ("volume", 5), "teaspoons": ("volume", 5),
    "quart": ("volume", 946), "quarts": ("volume", 946),
    "pint": ("volume", 473), "pints": ("volume", 473),
    "fl": ("volume", 29.6),  # "fl oz" -> unit token is "fl", "oz" consumed below
    "clove": ("count", 1), "cloves": ("count", 1),
    "can": ("count", 1), "cans": ("count", 1),
    "jar": ("count", 1), "jars": ("count", 1),
    "bunch": ("count", 1), "bunches": ("count", 1),
    "head": ("count", 1), "heads": ("count", 1),
    "stalk": ("count", 1), "stalks": ("count", 1),
    "sprig": ("count", 1), "sprigs": ("count", 1),
    "slice": ("count", 1), "slices": ("count", 1),
    "piece": ("count", 1), "pieces": ("count", 1),
    "package": ("count", 1), "packages": ("count", 1), "pkg": ("count", 1),
}

UNICODE_FRACTIONS = {
    "½": 0.5, "⅓": 1 / 3, "⅔": 2 / 3, "¼": 0.25, "¾": 0.75,
    "⅕": 0.2, "⅖": 0.4, "⅗": 0.6, "⅘": 0.8,
    "⅙": 1 / 6, "⅚": 5 / 6, "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875,
}

ADJECTIVES = {
    "large", "small", "medium", "big", "fresh", "freshly", "ripe", "raw",
    "whole", "boneless", "skinless", "extra", "finely", "roughly", "thinly",
    "cooked", "uncooked", "dried", "dry", "frozen", "canned", "organic",
    "chopped", "diced", "sliced", "minced", "grated", "shredded", "crushed",
}

_QTY_RE = re.compile(
    r"^\s*(?P<qty>\d+\s+\d+/\d+|\d+/\d+|\d*\.\d+|\d+(?:\s*[-–—]\s*\d+(?:\.\d+)?)?|[½⅓⅔¼¾⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞])"
    r"\s*(?P<rest>.*)$"
)


@dataclass
class ParsedIngredient:
    qty: float | None
    unit: str | None       # canonical base unit ('g'/'ml') or count-ish unit name, None if unitless
    dimension: str | None  # 'mass' | 'volume' | 'count' | None
    name: str
    raw: str


def _parse_qty(text: str) -> float:
    text = text.strip()
    if text in UNICODE_FRACTIONS:
        return UNICODE_FRACTIONS[text]
    range_match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*[-–—]\s*(\d+(?:\.\d+)?)", text)
    if range_match:
        return (float(range_match.group(1)) + float(range_match.group(2))) / 2
    mixed = re.fullmatch(r"(\d+)\s+(\d+)/(\d+)", text)
    if mixed:
        return int(mixed.group(1)) + int(mixed.group(2)) / int(mixed.group(3))
    frac = re.fullmatch(r"(\d+)/(\d+)", text)
    if frac:
        return int(frac.group(1)) / int(frac.group(2))
    return float(text)


def normalize_name(name: str) -> str:
    n = name.lower().strip()
    n = n.split(",")[0]
    n = re.sub(r"\(.*?\)", "", n)
    n = re.sub(r"\s+", " ", n).strip(" .;:")
    words = [w for w in n.split() if w not in ADJECTIVES and w != "of"]
    n = " ".join(words) if words else n
    # naive singularization with an exception list
    keep_s = {"hummus", "couscous", "asparagus", "molasses", "swiss", "watercress"}
    if n in keep_s or n.endswith("ss"):
        return n
    if n.endswith(("ches", "shes", "oes")):
        return n[:-2]
    if n.endswith("ies"):
        return n[:-3] + "y"
    if n.endswith("s"):
        return n[:-1]
    return n


def parse_ingredient(line: str) -> ParsedIngredient:
    raw = line.strip()
    # leading unicode fraction glued to a number, e.g. "1½"
    text = re.sub(
        r"(\d)([½⅓⅔¼¾⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞])",
        lambda m: str(int(m.group(1)) + UNICODE_FRACTIONS[m.group(2)]),
        raw,
    )
    m = _QTY_RE.match(text)
    if not m:
        return ParsedIngredient(None, None, None, normalize_name(raw), raw)
    try:
        qty = _parse_qty(m.group("qty"))
    except ValueError:
        return ParsedIngredient(None, None, None, normalize_name(raw), raw)

    rest = m.group("rest").strip()
    words = rest.split()
    unit = None
    dimension = None
    if words:
        candidate = words[0].lower().strip(".").rstrip(")").lstrip("(")
        if candidate in UNITS:
            dimension, factor = UNITS[candidate]
            qty *= factor
            unit = {"mass": "g", "volume": "ml", "count": candidate}[dimension]
            words = words[1:]
            # consume trailing "oz" of "fl oz"
            if candidate == "fl" and words and words[0].lower().strip(".") in ("oz", "ounce", "ounces"):
                words = words[1:]
    name_part = " ".join(words) or raw
    name = normalize_name(name_part)
    if dimension is None:
        dimension = "count"
        unit = None
    return ParsedIngredient(qty, unit, dimension, name, raw)


def _render_qty(qty: float, unit: str | None, dimension: str) -> str:
    if dimension == "mass":
        return f"{qty / 1000:g} kg" if qty >= 1000 else f"{round(qty):g} g"
    if dimension == "volume":
        return f"{qty / 1000:g} l" if qty >= 1000 else f"{round(qty):g} ml"
    q = round(qty, 1)
    q = int(q) if q == int(q) else q
    return f"{q} {unit}" if unit else f"{q}"


def generate_shopping_list(conn: sqlite3.Connection, plan_id: int | None = None) -> dict:
    plan = store.get_plan(conn, plan_id)
    slots = [s for s in plan["slots"] if s["recipe_url"]]
    if not slots:
        return {
            "plan": plan["name"],
            "items": [],
            "unparsed": [],
            "notes": ["No recipes assigned to any slot yet — assign recipes first."],
            "text": "",
        }

    notes: list[str] = []
    groups: dict[tuple[str, str], dict] = {}
    unparsed: list[dict] = []

    for slot in slots:
        recipe = store.get_recipe_by_url(conn, slot["recipe_url"])
        if recipe is None:
            notes.append(f"recipe for {slot['day']} {slot['meal']} missing from cache")
            continue
        servings = recipe["servings"]
        if not servings:
            servings = DEFAULT_SERVINGS
            notes.append(
                f"'{recipe['title']}' has unknown servings; assumed {DEFAULT_SERVINGS}"
            )
        n_attendees = len(slot["attendees"]) or servings
        factor = n_attendees / servings
        slot_label = f"{slot['day']} {slot['meal']}"

        for line in recipe["ingredients"]:
            parsed = parse_ingredient(line)
            if parsed.qty is None:
                unparsed.append(
                    {
                        "raw": parsed.raw,
                        "recipe": recipe["title"],
                        "note": f"for {n_attendees} people (recipe serves {servings})",
                    }
                )
                continue
            key = (parsed.name, parsed.dimension or "count")
            group = groups.setdefault(
                key,
                {
                    "name": parsed.name,
                    "dimension": parsed.dimension,
                    "unit": parsed.unit,
                    "qty": 0.0,
                    "from_recipes": [],
                    "raw_lines": [],
                },
            )
            group["qty"] += parsed.qty * factor
            if slot_label not in group["from_recipes"]:
                group["from_recipes"].append(slot_label)
            group["raw_lines"].append(parsed.raw)

    items = []
    for group in sorted(groups.values(), key=lambda g: g["name"]):
        items.append(
            {
                "name": group["name"],
                "quantity": round(group["qty"], 2),
                "unit": group["unit"],
                "display": f"{_render_qty(group['qty'], group['unit'], group['dimension'])} {group['name']}",
                "from_recipes": group["from_recipes"],
                "raw_lines": group["raw_lines"],
            }
        )

    lines = [f"🛒 Shopping list — {plan['name']}", ""]
    for item in items:
        lines.append(f"- {item['display']} ({', '.join(item['from_recipes'])})")
    if unparsed:
        lines += ["", "Check manually (couldn't parse amounts):"]
        for u in unparsed:
            lines.append(f"- {u['raw']} — {u['recipe']}, {u['note']}")
    text = "\n".join(lines)

    return {"plan": plan["name"], "items": items, "unparsed": unparsed, "notes": notes, "text": text}
