import json

import pytest

from mealplanner import search, store


def fake_ddg(monkeypatch, results_by_query):
    """Monkeypatch DDGS().text to return canned results."""
    calls = []

    class FakeDDGS:
        def text(self, q, max_results=10):
            calls.append(q)
            for key, results in results_by_query.items():
                if key in q:
                    return results
            return []

    monkeypatch.setattr(search, "DDGS", FakeDDGS)
    monkeypatch.setattr(search.time, "sleep", lambda s: None)
    return calls


def recipe_html(title, ingredients, servings=4):
    data = {
        "@context": "https://schema.org",
        "@type": "Recipe",
        "name": title,
        "recipeYield": f"{servings} servings",
        "totalTime": "PT30M",
        "recipeIngredient": ingredients,
        "recipeInstructions": [{"@type": "HowToStep", "text": "Cook it."}],
    }
    return f'<html><head><script type="application/ld+json">{json.dumps(data)}</script></head><body></body></html>'


PAGES = {
    "https://alpha.com/lentil-curry": recipe_html(
        "Lentil Curry", ["2 cups red lentils", "1 can coconut milk", "curry powder"]
    ),
    "https://alpha.com/chicken-soup": recipe_html(
        "Chicken Soup", ["1 whole chicken", "4 cups chicken broth", "2 carrots"]
    ),
    "https://beta.org/potato-stew": recipe_html(
        "Potato Stew", ["1 kg potatoes", "2 onions", "vegetable stock"]
    ),
}


def fetcher(url):
    return PAGES[url]


@pytest.fixture
def seeded(conn):
    store.add_website(conn, "alpha.com")
    store.add_website(conn, "beta.org")
    store.upsert_member(conn, "B", 34, hard_constraints=["vegan"])
    return conn


def test_build_queries_chunking():
    qs = search.build_queries("pasta", ["a.com", "b.com", "c.com", "d.com", "e.com"])
    assert len(qs) == 2
    assert "site:a.com OR site:b.com OR site:c.com OR site:d.com" in qs[0]
    assert qs[1] == "pasta recipe site:e.com"


def test_ddg_offsite_results_filtered_and_interleaved(monkeypatch, seeded):
    fake_ddg(
        monkeypatch,
        {
            "pasta": [
                {"href": "https://alpha.com/1"},
                {"href": "https://alpha.com/2"},
                {"href": "https://evil.com/spam"},
                {"href": "https://www.beta.org/3"},
            ]
        },
    )
    urls = search.ddg_search("pasta", ["alpha.com", "beta.org"], [])
    assert "https://evil.com/spam" not in urls
    # round-robin: alternates domains while both have entries
    assert urls == ["https://alpha.com/1", "https://www.beta.org/3", "https://alpha.com/2"]


def test_search_flags_violations_and_ranks_them_last(monkeypatch, seeded):
    fake_ddg(
        monkeypatch,
        {
            "dinner": [
                {"href": "https://alpha.com/chicken-soup"},
                {"href": "https://alpha.com/lentil-curry"},
                {"href": "https://beta.org/potato-stew"},
            ]
        },
    )
    out = search.search_recipes(seeded, "dinner", ["B"], fetcher=fetcher)
    titles = [r["title"] for r in out["results"]]
    assert len(titles) == 3
    # chicken soup violates vegan -> demoted to last despite best search rank
    assert titles[-1] == "Chicken Soup"
    soup = out["results"][-1]
    assert soup["constraint_violations"][0]["member"] == "B"
    assert out["skipped"] == []


def test_disliked_urls_excluded_liked_boosts_similar(monkeypatch, seeded):
    conn = seeded
    # dislike potato-stew directly; like a lentil recipe
    stew = store.upsert_recipe(
        conn,
        {"url": "https://beta.org/potato-stew", "title": "Potato Stew",
         "ingredients": ["potatoes"], "servings": 4},
    )
    store.record_feedback(conn, stew["id"], "disliked")
    liked = store.upsert_recipe(
        conn,
        {"url": "https://old.com/dal", "title": "Red Lentil Dal",
         "ingredients": ["red lentils", "coconut milk"], "servings": 4},
    )
    store.record_feedback(conn, liked["id"], "liked")

    fake_ddg(
        monkeypatch,
        {
            "dinner": [
                {"href": "https://alpha.com/chicken-soup"},
                {"href": "https://beta.org/potato-stew"},
                {"href": "https://alpha.com/lentil-curry"},
            ]
        },
    )
    out = search.search_recipes(conn, "dinner", [], fetcher=fetcher)
    urls = [r["url"] for r in out["results"]]
    assert "https://beta.org/potato-stew" not in urls  # excluded, not just demoted
    assert any("disliked" in n for n in out["notes"])
    # lentil curry overlaps the liked dal -> outranks chicken soup despite worse search rank
    assert urls[0] == "https://alpha.com/lentil-curry"


def test_unparseable_page_goes_to_skipped(monkeypatch, seeded):
    fake_ddg(monkeypatch, {"dinner": [{"href": "https://alpha.com/broken"}]})

    def bad_fetcher(url):
        return "<html><body>404 not found</body></html>"

    out = search.search_recipes(seeded, "dinner", [], fetcher=bad_fetcher)
    assert out["results"] == []
    assert out["skipped"][0]["url"] == "https://alpha.com/broken"


def test_no_websites_returns_note(conn):
    out = search.search_recipes(conn, "dinner", [])
    assert out["results"] == []
    assert "No websites" in out["notes"][0]


def test_cached_recipe_skips_fetch(monkeypatch, seeded):
    conn = seeded
    store.upsert_recipe(
        conn,
        {"url": "https://alpha.com/cached", "title": "Cached Curry", "site": "alpha.com",
         "ingredients": ["chickpeas"], "servings": 2},
    )
    fake_ddg(monkeypatch, {"dinner": [{"href": "https://alpha.com/cached"}]})

    def exploding_fetcher(url):
        raise AssertionError("should not fetch cached URL")

    out = search.search_recipes(conn, "dinner", [], fetcher=exploding_fetcher)
    assert out["results"][0]["title"] == "Cached Curry"
