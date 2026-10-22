"""
Multi-Tenant Scoping Tests für Todos.

Stellt sicher, dass User NUR auf Todos ihres eigenen Households
zugreifen können. Cross-Household-Zugriffe müssen mit 403 abgelehnt werden.
"""



# ---------------------------------------------------------------------------
# Positiv: User A liest eigene Todos → 200
# ---------------------------------------------------------------------------


def test_user_a_can_read_own_todos(client, household_a, token_a, todo_a):
    """GET eigene Todos liefert 200 und enthält das eigene Todo."""
    resp = client.get(
        f"/api/households/{household_a.id}/todos/?include_done=true",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(t["id"] == str(todo_a.id) for t in data)


# ---------------------------------------------------------------------------
# Negativ: User A liest Todos von Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_read_other_household_todos(
    client, household_b, token_a, todo_b
):
    """GET fremde Todos liefert 403 Forbidden."""
    resp = client.get(
        f"/api/households/{household_b.id}/todos/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Negativ: User A erstellt Todo in Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_create_in_other_household(
    client, household_b, token_a, user_b
):
    """POST in fremden Household liefert 403 Forbidden."""
    resp = client.post(
        f"/api/households/{household_b.id}/todos/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": "Hacker-Todo"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Negativ: User A patcht Todo in Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_patch_other_household_todo(
    client, household_b, token_a, todo_b
):
    """PATCH auf fremdes Todo liefert 403 Forbidden."""
    resp = client.patch(
        f"/api/households/{household_b.id}/todos/{todo_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": "Gehacktes Todo"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Negativ: User A löscht Todo in Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_delete_other_household_todo(
    client, household_b, token_a, todo_b
):
    """DELETE auf fremdes Todo liefert 403 Forbidden."""
    resp = client.delete(
        f"/api/households/{household_b.id}/todos/{todo_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


def test_todo_assignee_must_be_current_household_member(
    client, db, household_a, token_a, user_a, user_b, todo_a
):
    import uuid

    headers = {"Authorization": f"Bearer {token_a}"}
    url = f"/api/households/{household_a.id}/todos/"
    for outsider in (user_b.id, uuid.uuid4()):
        assert client.post(url, headers=headers, json={
            "title": "Scoped assignee", "assigned_to_user_id": str(outsider),
        }).status_code == 422
        assert client.patch(url + str(todo_a.id), headers=headers, json={
            "assigned_to_user_id": str(outsider),
        }).status_code == 422
    valid = client.post(url, headers=headers, json={
        "title": "Scoped assignee", "assigned_to_user_id": str(user_a.id),
    })
    assert valid.status_code == 201
    assert valid.json()["assigned_to_user_id"] == str(user_a.id)
    unassigned = client.patch(url + valid.json()["id"], headers=headers, json={
        "assigned_to_user_id": None,
    })
    assert unassigned.status_code == 200
    assert unassigned.json()["assigned_to_user_id"] is None
