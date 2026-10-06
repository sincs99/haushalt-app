"""Rezepte: Zubereitungsschritte und Tags (neu mit dem KI-Assistenten)."""


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_create_recipe_with_steps_and_tags(client, token_a, household_a, user_a):
    res = client.post(
        f"/api/households/{household_a.id}/recipes/",
        json={"name": "Pfannkuchen", "ingredients": ["200 g Mehl"], "steps": ["Teig rühren.", "Ausbacken."], "tags": ["schnell"]},
        headers=_auth(token_a),
    )
    assert res.status_code == 201
    assert res.json()["steps"] == ["Teig rühren.", "Ausbacken."]
    assert res.json()["tags"] == ["schnell"]


def test_existing_recipe_defaults_to_empty_lists(client, token_a, recipe_a):
    res = client.get(f"/api/households/{recipe_a.household_id}/recipes/{recipe_a.id}", headers=_auth(token_a))
    assert res.json()["steps"] == []
    assert res.json()["tags"] == []


def test_patch_steps_null_becomes_empty(client, token_a, recipe_a):
    url = f"/api/households/{recipe_a.household_id}/recipes/{recipe_a.id}"
    client.patch(url, json={"steps": ["Kochen."]}, headers=_auth(token_a))
    res = client.patch(url, json={"steps": None, "tags": None}, headers=_auth(token_a))
    assert res.status_code == 200
    assert res.json()["steps"] == []
    assert res.json()["tags"] == []


def test_steps_and_tags_are_validated(client, token_a, household_a, user_a):
    url = f"/api/households/{household_a.id}/recipes/"
    for body in (
        {"name": "X", "steps": ["  "]},
        {"name": "X", "steps": ["s" * 1001]},
        {"name": "X", "tags": ["t" * 31]},
        {"name": "X", "tags": [f"t{i}" for i in range(11)]},
    ):
        assert client.post(url, json=body, headers=_auth(token_a)).status_code == 422
