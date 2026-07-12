import pytest

from mealplanner import shopping, store
from mealplanner.shopping import parse_ingredient


@pytest.mark.parametrize(
    "line,qty,unit,dimension,name",
    [
        ("2 cups flour", 480, "ml", "volume", "flour"),
        ("½ tsp salt", 2.5, "ml", "volume", "salt"),
        ("1 1/2 lbs chicken thighs, trimmed", 680.4, "g", "mass", "chicken thigh"),
        ("1½ cups sugar", 360, "ml", "volume", "sugar"),
        ("500 g pumpkin, diced", 500, "g", "mass", "pumpkin"),
        ("1.5 kg potatoes", 1500, "g", "mass", "potato"),
        ("2-3 carrots", 2.5, None, "count", "carrot"),
        ("3 cloves garlic, minced", 3, "cloves", "count", "garlic"),
        ("1 can (400g) chopped tomatoes", 1, "can", "count", "tomato"),
        ("2 large onions", 2, None, "count", "onion"),
        ("4 fl oz milk", 118.4, "ml", "volume", "milk"),
        ("2 peaches", 2, None, "count", "peach"),
        ("100 g berries", 100, "g", "mass", "berry"),
    ],
)
def test_parse_ingredient(line, qty, unit, dimension, name):
    p = parse_ingredient(line)
    assert p.qty == pytest.approx(qty, rel=0.01)
    assert p.unit == unit
    assert p.dimension == dimension
    assert p.name == name


@pytest.mark.parametrize("line", ["salt to taste", "olive oil for frying", "a pinch of saffron"])
def test_parse_unquantified_lines(line):
    p = parse_ingredient(line)
    assert p.qty is None
    assert p.raw == line


def _setup_plan(conn):
    store.upsert_member(conn, "A", 40)
    store.upsert_member(conn, "B", 34)
    store.upsert_recipe(
        conn,
        {
            "url": "https://x.com/stew",
            "title": "Stew",
            "servings": 4,
            "ingredients": ["1 kg potatoes", "2 onions", "salt to taste"],
        },
    )
    store.upsert_recipe(
        conn,
        {
            "url": "https://x.com/mash",
            "title": "Mash",
            "servings": 2,
            "ingredients": ["500 g potatoes", "100 ml milk"],
        },
    )
    plan = store.create_plan(
        conn,
        "Test week",
        [
            {"day": "Monday", "meal": "dinner", "attendees": ["A", "B"]},  # 2 of 4 servings
            {"day": "Tuesday", "meal": "lunch", "attendees": ["A", "B"]},  # 2 of 2 servings
        ],
    )
    r1 = store.get_recipe_by_url(conn, "https://x.com/stew")
    r2 = store.get_recipe_by_url(conn, "https://x.com/mash")
    store.assign_recipe(conn, plan["plan_id"], plan["slots"][0]["slot_id"], r1["id"])
    store.assign_recipe(conn, plan["plan_id"], plan["slots"][1]["slot_id"], r2["id"])
    return plan


def test_shopping_list_scales_and_consolidates(conn):
    plan = _setup_plan(conn)
    out = shopping.generate_shopping_list(conn, plan["plan_id"])

    by_name = {i["name"]: i for i in out["items"]}
    # stew scaled 2/4 -> 500 g potatoes; mash scaled 2/2 -> 500 g; consolidated 1 kg
    assert by_name["potato"]["quantity"] == pytest.approx(1000)
    assert by_name["potato"]["display"] == "1 kg potato"
    assert sorted(by_name["potato"]["from_recipes"]) == ["Monday dinner", "Tuesday lunch"]
    # onions scaled 2/4 -> 1
    assert by_name["onion"]["quantity"] == pytest.approx(1)
    assert by_name["milk"]["quantity"] == pytest.approx(100)

    assert len(out["unparsed"]) == 1
    assert out["unparsed"][0]["raw"] == "salt to taste"
    assert "🛒" in out["text"]
    assert "salt to taste" in out["text"]


def test_shopping_list_unknown_servings_assumes_default(conn):
    store.upsert_member(conn, "A", 40)
    store.upsert_recipe(
        conn,
        {"url": "https://x.com/mystery", "title": "Mystery", "servings": None,
         "ingredients": ["400 g rice"]},
    )
    plan = store.create_plan(
        conn, "W", [{"day": "Mon", "meal": "dinner", "attendees": ["A"]}]
    )
    r = store.get_recipe_by_url(conn, "https://x.com/mystery")
    store.assign_recipe(conn, plan["plan_id"], plan["slots"][0]["slot_id"], r["id"])
    out = shopping.generate_shopping_list(conn, plan["plan_id"])
    assert out["items"][0]["quantity"] == pytest.approx(100)  # 400 g * 1/4
    assert any("assumed 4" in n for n in out["notes"])


def test_shopping_list_empty_plan(conn):
    store.create_plan(conn, "Empty", [{"day": "Mon", "meal": "lunch", "attendees": []}])
    out = shopping.generate_shopping_list(conn)
    assert out["items"] == []
    assert "assign recipes first" in out["notes"][0]
