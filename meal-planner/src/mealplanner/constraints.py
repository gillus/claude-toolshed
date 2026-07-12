"""Resolve members' hard constraints into ingredient exclusion keywords and
check recipes against them.

A hard constraint is either a known diet tag ("vegan") that expands to a
curated keyword list, or a literal exclusion ("no pumpkin" -> "pumpkin").
Matching is word-boundary based over ingredient lines; matches produce
violation records — callers flag/demote, never silently drop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MEAT = [
    "beef", "pork", "chicken", "turkey", "duck", "lamb", "veal", "bacon",
    "ham", "prosciutto", "sausage", "salami", "chorizo", "meat", "steak",
    "mince", "pancetta", "guanciale", "speck",
]
FISH_SEAFOOD = [
    "fish", "salmon", "tuna", "cod", "anchovy", "anchovies", "sardine",
    "shrimp", "prawn", "crab", "lobster", "clam", "mussel", "oyster",
    "squid", "octopus", "scallop", "seafood",
]
DAIRY = [
    "milk", "butter", "cream", "cheese", "yogurt", "yoghurt", "mozzarella",
    "parmesan", "parmigiano", "pecorino", "ricotta", "mascarpone", "burrata",
    "gorgonzola", "feta", "ghee", "creme fraiche",
]
EGGS = ["egg", "eggs", "mayonnaise", "mayo", "aioli"]
GLUTEN = [
    "wheat", "flour", "bread", "breadcrumbs", "pasta", "spaghetti", "penne",
    "couscous", "barley", "rye", "semolina", "farro", "seitan", "soy sauce",
]
NUTS = [
    "almond", "walnut", "hazelnut", "cashew", "pistachio", "pecan",
    "macadamia", "peanut", "nut", "nuts",
]

DIET_TAGS: dict[str, list[str]] = {
    "vegan": MEAT + FISH_SEAFOOD + DAIRY + EGGS + ["honey", "gelatin", "lard"],
    "vegetarian": MEAT + FISH_SEAFOOD + ["gelatin", "lard"],
    "pescatarian": MEAT + ["gelatin", "lard"],
    "gluten free": GLUTEN,
    "gluten-free": GLUTEN,
    "no gluten": GLUTEN,
    "celiac": GLUTEN,
    "dairy free": DAIRY,
    "dairy-free": DAIRY,
    "no dairy": DAIRY,
    "lactose intolerant": DAIRY,
    "no lactose": DAIRY,
    "nut allergy": NUTS,
    "no nuts": NUTS,
    "nut free": NUTS,
    "no pork": ["pork", "bacon", "ham", "prosciutto", "salami", "chorizo",
                "pancetta", "guanciale", "speck", "lard"],
    "halal": ["pork", "bacon", "ham", "prosciutto", "salami", "chorizo",
              "pancetta", "guanciale", "speck", "lard", "wine", "beer", "alcohol"],
    "no shellfish": ["shrimp", "prawn", "crab", "lobster", "clam", "mussel",
                     "oyster", "squid", "octopus", "scallop", "shellfish"],
    "no eggs": EGGS,
    "egg allergy": EGGS,
}

# keyword -> ingredient words that contain it but must NOT count as a match
EXCEPTIONS: dict[str, list[str]] = {
    "egg": ["eggplant", "eggplants"],
    "nut": ["nutmeg", "nutritional", "coconut", "butternut"],
    "nuts": ["coconuts"],
    "meat": ["nutmeat"],
    "milk": ["coconut milk", "oat milk", "almond milk", "soy milk", "rice milk"],
    "cream": ["coconut cream", "cream of tartar"],
    "butter": ["peanut butter", "almond butter", "cocoa butter", "butternut"],
    "fish": ["fish-free"],
}

_STRIP_PREFIXES = ("no ", "allergic to ", "allergy to ", "avoid ", "hates ", "can't eat ", "cannot eat ")


@dataclass
class Violation:
    member: str
    constraint: str
    matched_ingredient: str

    def as_dict(self) -> dict:
        return {
            "member": self.member,
            "constraint": self.constraint,
            "matched_ingredient": self.matched_ingredient,
        }


def expand_constraint(text: str) -> list[str]:
    """Map one hard-constraint string to lowercase exclusion keywords."""
    t = text.strip().lower()
    if t in DIET_TAGS:
        return DIET_TAGS[t]
    for prefix in _STRIP_PREFIXES:
        if t.startswith(prefix):
            t = t[len(prefix):]
            break
    return [t] if t else []


def _keyword_matches(keyword: str, line: str) -> bool:
    if not re.search(rf"\b{re.escape(keyword)}s?\b", line):
        return False
    for exception in EXCEPTIONS.get(keyword, []):
        if exception in line:
            # the keyword hit might be entirely explained by the exception phrase;
            # re-check the line with the exception removed
            if not re.search(rf"\b{re.escape(keyword)}s?\b", line.replace(exception, "")):
                return False
    return True


def check_recipe(
    ingredients: list[str], members: list[dict]
) -> list[dict]:
    """Check ingredient lines against each member's hard constraints.

    members: [{name, hard_constraints: [...]}]. Returns violation dicts.
    """
    violations: list[Violation] = []
    lines = [i.lower() for i in ingredients]
    for member in members:
        for constraint in member.get("hard_constraints", []):
            hit = None
            for keyword in expand_constraint(constraint):
                for raw, line in zip(ingredients, lines):
                    if _keyword_matches(keyword, line):
                        hit = Violation(member["name"], constraint, raw)
                        break
                if hit:
                    break
            if hit:
                violations.append(hit)
    return [v.as_dict() for v in violations]
