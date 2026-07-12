import pytest

from mealplanner import store


def make_recipe(conn, url="https://ex.com/r1", title="Pasta", servings=4, ingredients=None):
    return store.upsert_recipe(
        conn,
        {
            "url": url,
            "title": title,
            "site": "ex.com",
            "servings": servings,
            "yields_raw": f"{servings} servings",
            "total_time_min": 30,
            "ingredients": ingredients or ["2 cups flour", "1 egg"],
            "instructions": "Mix and cook.",
        },
    )


def test_upsert_member_creates_and_replaces(conn):
    m = store.upsert_member(conn, "B", 34, hard_constraints=["vegan"], likes=["pasta"])
    assert m["hard_constraints"] == ["vegan"]
    assert m["likes"] == ["pasta"]

    m = store.upsert_member(conn, "B", 35, hard_constraints=["vegan", "no nuts"])
    assert m["age"] == 35
    assert m["hard_constraints"] == ["vegan", "no nuts"]
    assert m["likes"] == []  # fully replaced
    assert len(store.list_members(conn)) == 1


def test_member_name_case_insensitive(conn):
    store.upsert_member(conn, "Carla", 10)
    assert store.get_member(conn, "carla")["name"] == "Carla"


def test_get_missing_member_lists_known(conn):
    store.upsert_member(conn, "B", 34)
    with pytest.raises(store.NotFoundError, match="B"):
        store.get_member(conn, "Zed")


def test_remove_member_cascades_preferences(conn):
    store.upsert_member(conn, "B", 34, likes=["pasta"])
    assert store.remove_member(conn, "B") is True
    assert store.remove_member(conn, "B") is False
    assert conn.execute("SELECT COUNT(*) c FROM preferences").fetchone()["c"] == 0


def test_websites_normalized_and_deduped(conn):
    store.add_website(conn, "https://www.SeriousEats.com/recipes/thing")
    store.add_website(conn, "seriouseats.com")
    assert store.list_websites(conn) == ["seriouseats.com"]
    store.remove_website(conn, "www.seriouseats.com")
    assert store.list_websites(conn) == []


def test_add_website_rejects_garbage(conn):
    with pytest.raises(ValueError):
        store.add_website(conn, "not a domain")


def test_recipe_upsert_and_cache_age(conn):
    r = make_recipe(conn)
    assert r["ingredients"] == ["2 cups flour", "1 egg"]
    r2 = make_recipe(conn, title="Pasta v2")
    assert r2["id"] == r["id"]
    assert r2["title"] == "Pasta v2"
    assert store.get_recipe_by_url(conn, r["url"], max_age_days=30)["id"] == r["id"]
    conn.execute("UPDATE recipes SET fetched_at = datetime('now', '-40 days')")
    assert store.get_recipe_by_url(conn, r["url"], max_age_days=30) is None
    assert store.get_recipe_by_url(conn, r["url"]) is not None


def test_feedback_upsert_semantics(conn):
    r = make_recipe(conn)
    store.upsert_member(conn, "B", 34)
    b_id = store.get_member(conn, "B")["id"]

    store.record_feedback(conn, r["id"], "liked", member_id=b_id)
    store.record_feedback(conn, r["id"], "disliked", member_id=b_id, notes="too salty")
    fb = store.list_feedback(conn, member_id=b_id)
    assert len(fb) == 1
    assert fb[0]["verdict"] == "disliked"

    # family-level uniqueness enforced despite NULL member_id
    store.record_feedback(conn, r["id"], "liked")
    store.record_feedback(conn, r["id"], "liked")
    assert len(store.list_feedback(conn)) == 2  # one member row + one family row
    assert store.feedback_urls(conn, "liked") == {r["url"]}


def test_plan_roundtrip(conn):
    store.upsert_member(conn, "A", 40)
    store.upsert_member(conn, "B", 34)
    plan = store.create_plan(
        conn,
        "Week 1",
        [
            {"day": "Monday", "meal": "Lunch", "attendees": ["A"]},
            {"day": "Monday", "meal": "dinner", "attendees": ["A", "B"]},
        ],
    )
    assert len(plan["slots"]) == 2
    assert plan["slots"][1]["attendees"] == ["A", "B"]
    assert plan["slots"][0]["meal"] == "lunch"

    r = make_recipe(conn)
    store.assign_recipe(conn, plan["plan_id"], plan["slots"][0]["slot_id"], r["id"])
    got = store.get_plan(conn, plan["plan_id"])
    assert got["slots"][0]["recipe_title"] == "Pasta"

    store.update_slot(conn, plan["plan_id"], plan["slots"][0]["slot_id"],
                      attendees=["B"], clear_recipe=True)
    got = store.get_plan(conn)  # default = latest
    assert got["slots"][0]["attendees"] == ["B"]
    assert got["slots"][0]["recipe_url"] is None


def test_plan_validates_member_names_before_insert(conn):
    store.upsert_member(conn, "A", 40)
    with pytest.raises(store.NotFoundError):
        store.create_plan(conn, "bad", [{"day": "Mon", "meal": "lunch", "attendees": ["Nobody"]}])
    assert conn.execute("SELECT COUNT(*) c FROM meal_plans").fetchone()["c"] == 0


def test_get_plan_lists_others(conn):
    store.create_plan(conn, "W1", [{"day": "Mon", "meal": "lunch", "attendees": []}])
    p2 = store.create_plan(conn, "W2", [{"day": "Tue", "meal": "dinner", "attendees": []}])
    got = store.get_plan(conn)
    assert got["plan_id"] == p2["plan_id"]
    assert [p["name"] for p in got["other_plans"]] == ["W1"]
