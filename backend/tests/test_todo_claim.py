"""Tests für POST /todos/{id}/claim."""
import uuid


def test_claim_free_todo(client, household_a, token_a, user_a, db):
    """Claim auf freies Todo → 200, Aufrufer ist zuständig."""
    from app.models import Todo

    todo = Todo(household_id=household_a.id, title="Freies Todo")
    db.add(todo)
    db.commit()
    db.refresh(todo)

    resp = client.post(
        f"/api/households/{household_a.id}/todos/{todo.id}/claim",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["assignee_ids"] == [str(user_a.id)]
    assert data["assigned_to_user_id"] == str(user_a.id)  # Übergangsfeld


def test_claim_already_assigned_to_someone_else(client, household_a, token_a, user_a, user_a2, db):
    """Claim auf Todo einer anderen Person → 200, beide zuständig ("Ich helfe mit")."""
    from app.models import Todo

    todo = Todo(
        household_id=household_a.id,
        title="Vergebenes Todo",
        assignee_ids=[user_a2.id],
    )
    db.add(todo)
    db.commit()
    db.refresh(todo)

    resp = client.post(
        f"/api/households/{household_a.id}/todos/{todo.id}/claim",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    assert sorted(resp.json()["assignee_ids"]) == sorted([str(user_a.id), str(user_a2.id)])


def test_claim_cross_household(client, household_a, household_b, token_a, db):
    """Claim in fremdem Household → 403."""
    from app.models import Todo

    todo = Todo(household_id=household_b.id, title="Fremdes Todo")
    db.add(todo)
    db.commit()
    db.refresh(todo)

    resp = client.post(
        f"/api/households/{household_b.id}/todos/{todo.id}/claim",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


def test_claim_not_found(client, household_a, token_a):
    """Claim auf nicht existierendes Todo → 404."""
    fake_id = uuid.uuid4()
    resp = client.post(
        f"/api/households/{household_a.id}/todos/{fake_id}/claim",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 404
