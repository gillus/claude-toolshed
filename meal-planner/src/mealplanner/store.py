"""All database reads/writes. Every function takes an explicit connection."""

from __future__ import annotations

import json
import sqlite3
from urllib.parse import urlparse


class NotFoundError(ValueError):
    pass


# ---------------------------------------------------------------- members

def upsert_member(
    conn: sqlite3.Connection,
    name: str,
    age: int | None = None,
    hard_constraints: list[str] | None = None,
    likes: list[str] | None = None,
    dislikes: list[str] | None = None,
) -> dict:
    """Create a member or fully replace their profile (age + all preferences)."""
    row = conn.execute("SELECT id FROM members WHERE name = ?", (name,)).fetchone()
    if row:
        member_id = row["id"]
        conn.execute("UPDATE members SET age = ? WHERE id = ?", (age, member_id))
        conn.execute("DELETE FROM preferences WHERE member_id = ?", (member_id,))
    else:
        cur = conn.execute("INSERT INTO members (name, age) VALUES (?, ?)", (name, age))
        member_id = cur.lastrowid
    prefs = [("hard", t) for t in (hard_constraints or [])]
    prefs += [("like", t) for t in (likes or [])]
    prefs += [("dislike", t) for t in (dislikes or [])]
    conn.executemany(
        "INSERT OR IGNORE INTO preferences (member_id, kind, text) VALUES (?, ?, ?)",
        [(member_id, kind, text.strip()) for kind, text in prefs if text.strip()],
    )
    conn.commit()
    return get_member(conn, name)


def get_member(conn: sqlite3.Connection, name: str) -> dict:
    row = conn.execute("SELECT * FROM members WHERE name = ?", (name,)).fetchone()
    if not row:
        raise NotFoundError(f"No family member named {name!r}. Known members: "
                            + (", ".join(m["name"] for m in list_members(conn)) or "none"))
    prefs = conn.execute(
        "SELECT kind, text FROM preferences WHERE member_id = ? ORDER BY id", (row["id"],)
    ).fetchall()
    return {
        "id": row["id"],
        "name": row["name"],
        "age": row["age"],
        "hard_constraints": [p["text"] for p in prefs if p["kind"] == "hard"],
        "likes": [p["text"] for p in prefs if p["kind"] == "like"],
        "dislikes": [p["text"] for p in prefs if p["kind"] == "dislike"],
    }


def list_members(conn: sqlite3.Connection) -> list[dict]:
    names = [r["name"] for r in conn.execute("SELECT name FROM members ORDER BY name")]
    return [get_member(conn, n) for n in names]


def remove_member(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute("DELETE FROM members WHERE name = ?", (name,))
    conn.commit()
    return cur.rowcount > 0


def member_ids(conn: sqlite3.Connection, names: list[str]) -> dict[str, int]:
    """Resolve names to ids, raising with the full known list on any miss."""
    return {name: get_member(conn, name)["id"] for name in names}


# ---------------------------------------------------------------- websites

def normalize_domain(domain: str) -> str:
    d = domain.strip().lower()
    if "://" in d:
        d = urlparse(d).netloc
    d = d.split("/")[0]
    if d.startswith("www."):
        d = d[4:]
    return d


def add_website(conn: sqlite3.Connection, domain: str) -> list[str]:
    d = normalize_domain(domain)
    if not d or "." not in d:
        raise ValueError(f"{domain!r} does not look like a domain (expected e.g. 'seriouseats.com')")
    conn.execute("INSERT OR IGNORE INTO websites (domain) VALUES (?)", (d,))
    conn.commit()
    return list_websites(conn)


def remove_website(conn: sqlite3.Connection, domain: str) -> list[str]:
    conn.execute("DELETE FROM websites WHERE domain = ?", (normalize_domain(domain),))
    conn.commit()
    return list_websites(conn)


def list_websites(conn: sqlite3.Connection) -> list[str]:
    return [r["domain"] for r in conn.execute("SELECT domain FROM websites ORDER BY domain")]


# ---------------------------------------------------------------- recipes

def upsert_recipe(conn: sqlite3.Connection, recipe: dict) -> dict:
    """Insert or refresh a parsed recipe keyed by URL. Expects keys:
    url, title, site, servings, yields_raw, total_time_min, ingredients (list), instructions."""
    conn.execute(
        """INSERT INTO recipes (url, title, site, servings, yields_raw, total_time_min,
                                ingredients_json, instructions, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(url) DO UPDATE SET
             title=excluded.title, site=excluded.site, servings=excluded.servings,
             yields_raw=excluded.yields_raw, total_time_min=excluded.total_time_min,
             ingredients_json=excluded.ingredients_json, instructions=excluded.instructions,
             fetched_at=excluded.fetched_at""",
        (
            recipe["url"],
            recipe.get("title"),
            recipe.get("site"),
            recipe.get("servings"),
            recipe.get("yields_raw"),
            recipe.get("total_time_min"),
            json.dumps(recipe.get("ingredients", [])),
            recipe.get("instructions"),
        ),
    )
    conn.commit()
    return get_recipe_by_url(conn, recipe["url"])  # type: ignore[return-value]


def _recipe_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "url": row["url"],
        "title": row["title"],
        "site": row["site"],
        "servings": row["servings"],
        "yields_raw": row["yields_raw"],
        "total_time_min": row["total_time_min"],
        "ingredients": json.loads(row["ingredients_json"]),
        "instructions": row["instructions"],
        "fetched_at": row["fetched_at"],
    }


def get_recipe_by_url(
    conn: sqlite3.Connection, url: str, max_age_days: int | None = None
) -> dict | None:
    row = conn.execute("SELECT * FROM recipes WHERE url = ?", (url,)).fetchone()
    if not row:
        return None
    if max_age_days is not None:
        fresh = conn.execute(
            "SELECT fetched_at >= datetime('now', ?) AS fresh FROM recipes WHERE id = ?",
            (f"-{max_age_days} days", row["id"]),
        ).fetchone()["fresh"]
        if not fresh:
            return None
    return _recipe_row_to_dict(row)


# ---------------------------------------------------------------- feedback

def record_feedback(
    conn: sqlite3.Connection,
    recipe_id: int,
    verdict: str,
    member_id: int | None = None,
    notes: str | None = None,
) -> None:
    if verdict not in ("liked", "disliked"):
        raise ValueError("verdict must be 'liked' or 'disliked'")
    if member_id is None:
        # SQLite UNIQUE treats NULLs as distinct, so enforce family-level uniqueness manually.
        conn.execute(
            "DELETE FROM feedback WHERE recipe_id = ? AND member_id IS NULL", (recipe_id,)
        )
        conn.execute(
            "INSERT INTO feedback (recipe_id, member_id, verdict, notes) VALUES (?, NULL, ?, ?)",
            (recipe_id, verdict, notes),
        )
    else:
        conn.execute(
            """INSERT INTO feedback (recipe_id, member_id, verdict, notes)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(recipe_id, member_id) DO UPDATE SET
                 verdict=excluded.verdict, notes=excluded.notes, created_at=datetime('now')""",
            (recipe_id, member_id, verdict, notes),
        )
    conn.commit()


def list_feedback(
    conn: sqlite3.Connection,
    verdict: str | None = None,
    member_id: int | None = None,
) -> list[dict]:
    q = """SELECT f.verdict, f.notes, f.created_at, r.url, r.title, m.name AS member
           FROM feedback f
           JOIN recipes r ON r.id = f.recipe_id
           LEFT JOIN members m ON m.id = f.member_id
           WHERE 1=1"""
    params: list = []
    if verdict:
        q += " AND f.verdict = ?"
        params.append(verdict)
    if member_id is not None:
        q += " AND f.member_id = ?"
        params.append(member_id)
    q += " ORDER BY f.created_at DESC"
    return [dict(r) for r in conn.execute(q, params)]


def feedback_urls(conn: sqlite3.Connection, verdict: str) -> set[str]:
    return {
        r["url"]
        for r in conn.execute(
            "SELECT DISTINCT r.url FROM feedback f JOIN recipes r ON r.id = f.recipe_id "
            "WHERE f.verdict = ?",
            (verdict,),
        )
    }


def feedback_recipes(conn: sqlite3.Connection, verdict: str) -> list[dict]:
    """Full recipe records having the given verdict (any member or family-level)."""
    rows = conn.execute(
        "SELECT DISTINCT r.* FROM feedback f JOIN recipes r ON r.id = f.recipe_id "
        "WHERE f.verdict = ?",
        (verdict,),
    ).fetchall()
    return [_recipe_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------- meal plans

def create_plan(
    conn: sqlite3.Connection,
    name: str,
    slots: list[dict],
    start_date: str | None = None,
) -> dict:
    """slots: [{day, meal, attendees: [names]}]. Validates all member names first."""
    all_names = {a for s in slots for a in s.get("attendees", [])}
    ids = member_ids(conn, sorted(all_names))
    cur = conn.execute(
        "INSERT INTO meal_plans (name, start_date) VALUES (?, ?)", (name, start_date)
    )
    plan_id = cur.lastrowid
    for slot in slots:
        sc = conn.execute(
            "INSERT INTO plan_slots (plan_id, day, meal) VALUES (?, ?, ?)",
            (plan_id, slot["day"], slot["meal"].lower()),
        )
        conn.executemany(
            "INSERT OR IGNORE INTO slot_attendees (slot_id, member_id) VALUES (?, ?)",
            [(sc.lastrowid, ids[a]) for a in slot.get("attendees", [])],
        )
    conn.commit()
    return get_plan(conn, plan_id)


def get_plan(conn: sqlite3.Connection, plan_id: int | None = None) -> dict:
    if plan_id is None:
        row = conn.execute("SELECT * FROM meal_plans ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            raise NotFoundError("No meal plans exist yet.")
    else:
        row = conn.execute("SELECT * FROM meal_plans WHERE id = ?", (plan_id,)).fetchone()
        if not row:
            raise NotFoundError(f"No meal plan with id {plan_id}.")
    slots = conn.execute(
        """SELECT s.id, s.day, s.meal, r.url AS recipe_url, r.title AS recipe_title,
                  r.servings AS recipe_servings
           FROM plan_slots s LEFT JOIN recipes r ON r.id = s.recipe_id
           WHERE s.plan_id = ? ORDER BY s.id""",
        (row["id"],),
    ).fetchall()
    out_slots = []
    for s in slots:
        attendees = [
            a["name"]
            for a in conn.execute(
                "SELECT m.name FROM slot_attendees sa JOIN members m ON m.id = sa.member_id "
                "WHERE sa.slot_id = ? ORDER BY m.name",
                (s["id"],),
            )
        ]
        out_slots.append(
            {
                "slot_id": s["id"],
                "day": s["day"],
                "meal": s["meal"],
                "attendees": attendees,
                "recipe_url": s["recipe_url"],
                "recipe_title": s["recipe_title"],
                "recipe_servings": s["recipe_servings"],
            }
        )
    others = [
        dict(r)
        for r in conn.execute(
            "SELECT id, name, created_at FROM meal_plans WHERE id != ? ORDER BY id DESC",
            (row["id"],),
        )
    ]
    return {
        "plan_id": row["id"],
        "name": row["name"],
        "start_date": row["start_date"],
        "created_at": row["created_at"],
        "slots": out_slots,
        "other_plans": others,
    }


def _get_slot(conn: sqlite3.Connection, plan_id: int, slot_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM plan_slots WHERE id = ? AND plan_id = ?", (slot_id, plan_id)
    ).fetchone()
    if not row:
        raise NotFoundError(f"No slot {slot_id} in plan {plan_id}.")
    return row


def update_slot(
    conn: sqlite3.Connection,
    plan_id: int,
    slot_id: int,
    attendees: list[str] | None = None,
    clear_recipe: bool = False,
) -> None:
    _get_slot(conn, plan_id, slot_id)
    if attendees is not None:
        ids = member_ids(conn, attendees)
        conn.execute("DELETE FROM slot_attendees WHERE slot_id = ?", (slot_id,))
        conn.executemany(
            "INSERT OR IGNORE INTO slot_attendees (slot_id, member_id) VALUES (?, ?)",
            [(slot_id, i) for i in ids.values()],
        )
    if clear_recipe:
        conn.execute("UPDATE plan_slots SET recipe_id = NULL WHERE id = ?", (slot_id,))
    conn.commit()


def assign_recipe(conn: sqlite3.Connection, plan_id: int, slot_id: int, recipe_id: int) -> None:
    _get_slot(conn, plan_id, slot_id)
    conn.execute("UPDATE plan_slots SET recipe_id = ? WHERE id = ?", (recipe_id, slot_id))
    conn.commit()
