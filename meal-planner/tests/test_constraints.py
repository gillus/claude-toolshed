from mealplanner import constraints


def vegan_member(name="B"):
    return {"name": name, "hard_constraints": ["vegan"]}


def test_vegan_catches_chicken_broth():
    v = constraints.check_recipe(["4 cups chicken broth", "1 onion"], [vegan_member()])
    assert len(v) == 1
    assert v[0]["member"] == "B"
    assert v[0]["constraint"] == "vegan"
    assert v[0]["matched_ingredient"] == "4 cups chicken broth"


def test_eggplant_does_not_trip_egg():
    v = constraints.check_recipe(["2 eggplants, cubed", "olive oil"], [vegan_member()])
    assert v == []


def test_egg_still_caught_when_eggplant_also_present():
    v = constraints.check_recipe(["1 eggplant", "2 eggs, beaten"], [vegan_member()])
    assert len(v) == 1
    assert v[0]["matched_ingredient"] == "2 eggs, beaten"


def test_coconut_milk_ok_for_dairy_free_but_milk_caught():
    member = {"name": "C", "hard_constraints": ["no dairy"]}
    assert constraints.check_recipe(["400 ml coconut milk"], [member]) == []
    v = constraints.check_recipe(["400 ml coconut milk", "1 cup whole milk"], [member])
    assert len(v) == 1
    assert "whole milk" in v[0]["matched_ingredient"]


def test_literal_constraint_no_pumpkin():
    member = {"name": "C", "hard_constraints": ["no pumpkin"]}
    v = constraints.check_recipe(["500 g pumpkin, diced"], [member])
    assert len(v) == 1
    assert v[0]["constraint"] == "no pumpkin"
    assert constraints.check_recipe(["500 g potatoes"], [member]) == []


def test_literal_constraint_matches_plural():
    member = {"name": "C", "hard_constraints": ["no mushroom"]}
    v = constraints.check_recipe(["200 g mushrooms, sliced"], [member])
    assert len(v) == 1


def test_multi_member_multi_constraint():
    members = [
        {"name": "B", "hard_constraints": ["vegan"]},
        {"name": "C", "hard_constraints": ["no pumpkin", "nut allergy"]},
    ]
    v = constraints.check_recipe(
        ["1 pumpkin", "100 g butter", "50 g walnuts"], members
    )
    found = {(x["member"], x["constraint"]) for x in v}
    assert found == {("B", "vegan"), ("C", "no pumpkin"), ("C", "nut allergy")}


def test_nutmeg_does_not_trip_nut_allergy():
    member = {"name": "C", "hard_constraints": ["nut allergy"]}
    assert constraints.check_recipe(["1 tsp nutmeg", "2 cups flour"], [member]) == []


def test_gluten_free_catches_soy_sauce():
    member = {"name": "D", "hard_constraints": ["gluten free"]}
    v = constraints.check_recipe(["2 tbsp soy sauce"], [member])
    assert len(v) == 1


def test_expand_unknown_prefix_stripped():
    assert constraints.expand_constraint("allergic to strawberries") == ["strawberries"]
    assert constraints.expand_constraint("No Pumpkin") == ["pumpkin"]
    assert constraints.expand_constraint("vegan") == constraints.DIET_TAGS["vegan"]
