"""Recipe search: DuckDuckGo site-restricted queries -> fetch -> parse -> rank."""

from __future__ import annotations

import re
import sqlite3
import time
from urllib.parse import urlparse

from ddgs import DDGS

from . import constraints, scrape, store

CHUNK_SIZE = 4          # domains per site:-OR group (long OR chains degrade DDG results)
DDG_RESULTS_PER_QUERY = 10
CACHE_MAX_AGE_DAYS = 30
FETCH_DELAY_S = 0.5

STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "with", "for", "to", "in", "on",
    "recipe", "recipes", "easy", "best", "quick", "simple", "homemade",
    "cup", "cups", "tbsp", "tsp", "teaspoon", "tablespoon", "g", "kg", "ml",
    "l", "oz", "lb", "large", "small", "medium", "fresh", "chopped", "diced",
    "sliced", "minced", "taste", "salt", "pepper", "oil", "olive", "water",
}


def _chunked(seq: list, n: int) -> list[list]:
    return [seq[i : i + n] for i in range(0, len(seq), n)]


def build_queries(query: str, domains: list[str]) -> list[str]:
    queries = []
    for chunk in _chunked(domains, CHUNK_SIZE):
        sites = " OR ".join(f"site:{d}" for d in chunk)
        queries.append(f"{query} recipe ({sites})" if len(chunk) > 1 else f"{query} recipe site:{chunk[0]}")
    return queries


def ddg_search(query: str, domains: list[str], notes: list[str]) -> list[str]:
    """Run chunked DDG queries; return candidate URLs interleaved round-robin by domain."""
    by_domain: dict[str, list[str]] = {d: [] for d in domains}
    seen: set[str] = set()
    for q in build_queries(query, domains):
        results = _ddg_text(q, notes)
        for r in results:
            url = r.get("href") or r.get("url") or ""
            if not url or url in seen:
                continue
            host = urlparse(url).netloc.lower().removeprefix("www.")
            domain = next((d for d in domains if host == d or host.endswith("." + d)), None)
            if domain is None:
                continue  # DDG ignored the site: filter for this result
            seen.add(url)
            by_domain[domain].append(url)
    # round-robin interleave for domain diversity
    ordered: list[str] = []
    queues = [urls for urls in by_domain.values() if urls]
    i = 0
    while queues:
        queue = queues[i % len(queues)]
        ordered.append(queue.pop(0))
        if not queue:
            queues.remove(queue)
        else:
            i += 1
    return ordered


def _ddg_text(q: str, notes: list[str]) -> list[dict]:
    for attempt in (1, 2):
        try:
            return list(DDGS().text(q, max_results=DDG_RESULTS_PER_QUERY))
        except Exception as e:
            if attempt == 1:
                time.sleep(2.0)
            else:
                notes.append(f"web search failed for query {q!r}: {e} "
                             "(possibly rate-limited; try again in a minute)")
    return []


def tokenize(recipe: dict) -> set[str]:
    text = (recipe.get("title") or "") + " " + " ".join(recipe.get("ingredients", []))
    tokens = re.findall(r"[a-z]+", text.lower())
    return {t for t in tokens if len(t) > 2 and t not in STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _query_tokens(query: str) -> set[str]:
    return {
        t for t in re.findall(r"[a-z]+", query.lower())
        if len(t) > 2 and t not in STOPWORDS
    }


def favorite_recipes(
    conn: sqlite3.Connection,
    query: str = "",
    members: list[dict] | None = None,
) -> list[dict]:
    """Liked recipes (excluding any later disliked), optionally filtered to
    those sharing a keyword with `query` and constraint-checked for members.
    Sorted by query similarity when a query is given."""
    qtokens = _query_tokens(query)
    disliked_urls = store.feedback_urls(conn, "disliked")
    out = []
    for r in store.feedback_recipes(conn, "liked"):
        if r["url"] in disliked_urls:
            continue
        tokens = tokenize(r)
        if qtokens and not tokens & qtokens:
            continue
        out.append(
            {
                "url": r["url"],
                "title": r["title"],
                "site": r["site"],
                "servings": r["servings"],
                "total_time_min": r["total_time_min"],
                "ingredients": r["ingredients"],
                "constraint_violations": constraints.check_recipe(
                    r["ingredients"], members or []
                ),
                "query_match": round(_jaccard(tokens, qtokens), 3) if qtokens else None,
            }
        )
    out.sort(key=lambda r: r["query_match"] or 0.0, reverse=True)
    return out


def score_recipe(
    recipe: dict,
    search_rank: int,
    liked_tokens: set[str],
    disliked_tokens: set[str],
    has_violation: bool,
) -> float:
    tokens = tokenize(recipe)
    return (
        -0.5 * search_rank
        + 2.0 * 10 * _jaccard(tokens, liked_tokens)
        - 3.0 * 10 * _jaccard(tokens, disliked_tokens)
        - 100.0 * has_violation
    )


def search_recipes(
    conn: sqlite3.Connection,
    query: str,
    attendees: list[str],
    max_results: int = 6,
    max_fetch: int = 8,
    fetcher=None,
) -> dict:
    """Full pipeline. `fetcher(url) -> html` is injectable for tests."""
    fetcher = fetcher or scrape.fetch_url
    notes: list[str] = []
    skipped: list[dict] = []

    domains = store.list_websites(conn)
    if not domains:
        return {
            "results": [],
            "skipped": [],
            "notes": ["No websites in the search pool. Add some with add_website first."],
        }

    members = [store.get_member(conn, name) for name in attendees]

    disliked_urls = store.feedback_urls(conn, "disliked")
    liked_tokens: set[str] = set()
    for r in store.feedback_recipes(conn, "liked"):
        liked_tokens |= tokenize(r)
    disliked_tokens: set[str] = set()
    for r in store.feedback_recipes(conn, "disliked"):
        disliked_tokens |= tokenize(r)

    # Liked recipes matching the query join the candidate pool straight from
    # the local DB — no fetch, no max_fetch slot used.
    favorites = favorite_recipes(conn, query, members) if _query_tokens(query) else []
    if favorites:
        notes.append(f"included {len(favorites)} liked favorite(s) matching the query")
    fav_urls = {f["url"] for f in favorites}

    candidates = ddg_search(query, domains, notes)
    dropped = [u for u in candidates if u in disliked_urls]
    if dropped:
        notes.append(f"excluded {len(dropped)} previously disliked recipe(s)")
    candidates = [
        u for u in candidates if u not in disliked_urls and u not in fav_urls
    ][:max_fetch]

    scored = []
    for fav in favorites:
        entry = dict(fav)
        entry.pop("query_match", None)
        entry["favorite"] = True
        entry["score"] = round(
            score_recipe(
                entry, 0, liked_tokens, disliked_tokens,
                bool(entry["constraint_violations"]),
            ),
            2,
        )
        scored.append(entry)
    for rank, url in enumerate(candidates):
        recipe = store.get_recipe_by_url(conn, url, max_age_days=CACHE_MAX_AGE_DAYS)
        if recipe is None:
            try:
                if rank > 0:
                    time.sleep(FETCH_DELAY_S)
                html = fetcher(url)
                recipe = scrape.parse_recipe(html, url)
                recipe = store.upsert_recipe(conn, recipe)
            except scrape.ScrapeError as e:
                skipped.append({"url": url, "reason": str(e)})
                continue
            except Exception as e:
                skipped.append({"url": url, "reason": f"{type(e).__name__}: {e}"})
                continue
        violations = constraints.check_recipe(recipe["ingredients"], members)
        score = score_recipe(recipe, rank, liked_tokens, disliked_tokens, bool(violations))
        scored.append(
            {
                "url": recipe["url"],
                "title": recipe["title"],
                "site": recipe["site"],
                "servings": recipe["servings"],
                "total_time_min": recipe["total_time_min"],
                "ingredients": recipe["ingredients"],
                "constraint_violations": violations,
                "favorite": False,
                "score": round(score, 2),
            }
        )

    scored.sort(key=lambda r: r["score"], reverse=True)
    return {"results": scored[:max_results], "skipped": skipped, "notes": notes}
