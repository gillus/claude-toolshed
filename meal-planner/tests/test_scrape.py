from pathlib import Path

import pytest

from mealplanner import scrape

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_jsonld_recipe():
    html = (FIXTURES / "jsonld_recipe.html").read_text()
    r = scrape.parse_recipe(html, "https://www.example.com/gratin")
    assert r["title"] == "Best Potato Gratin"
    assert r["site"] == "example.com"
    assert r["servings"] == 6
    assert r["total_time_min"] == 90
    assert len(r["ingredients"]) == 4
    assert "Preheat oven" in r["instructions"]


def test_parse_jsonld_fallback_when_recipe_scrapers_fails(monkeypatch):
    def boom(html, url):
        raise RuntimeError("recipe-scrapers exploded")

    monkeypatch.setattr(scrape, "_parse_with_recipe_scrapers", boom)
    html = (FIXTURES / "jsonld_recipe.html").read_text()
    r = scrape.parse_recipe(html, "https://example.com/gratin")
    assert r["title"] == "Best Potato Gratin"
    assert r["ingredients"][0].startswith("1 kg potatoes")


def test_parse_non_recipe_page_raises():
    html = (FIXTURES / "not_a_recipe.html").read_text()
    with pytest.raises(scrape.ScrapeError):
        scrape.parse_recipe(html, "https://example.com/about")


@pytest.mark.parametrize(
    "value,expected",
    [
        ("PT30M", 30),
        ("PT1H30M", 90),
        ("P1DT2H", 26 * 60),
        ("PT45S", 1),
        ("", None),
        (None, None),
        ("garbage", None),
    ],
)
def test_iso_duration(value, expected):
    assert scrape._iso_duration_to_minutes(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [("4 servings", 4), ("Serves 6", 6), ("12", 12), (8, 8), (None, None), ("a lot", None)],
)
def test_servings_from_yield(value, expected):
    assert scrape._servings_from_yield(value) == expected
