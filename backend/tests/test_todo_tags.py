"""Tests für Todo-Tags (JSON-Feld)."""

import pytest


def test_create_todo_with_tags(client, household_a, token_a):
    """Todo mit Tags erstellen → Tags im Response."""
    resp = client.post(
        f"/api/households/{household_a.id}/todos/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": "Mit Tags", "tags": ["dringend", "küche"]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["tags"] == ["dringend", "küche"]


def test_create_todo_default_tags(client, household_a, token_a):
    """Todo ohne Tags erstellen → leeres Array."""
    resp = client.post(
        f"/api/households/{household_a.id}/todos/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": "Ohne Tags"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["tags"] == []


def test_update_todo_tags(client, household_a, token_a):
    """Tags per PATCH ändern."""
    # Erstellen
    create_resp = client.post(
        f"/api/households/{household_a.id}/todos/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": "Update-Test", "tags": ["alt"]},
    )
    todo_id = create_resp.json()["id"]

    # Updaten
    update_resp = client.patch(
        f"/api/households/{household_a.id}/todos/{todo_id}",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"tags": ["neu", "wichtig"]},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["tags"] == ["neu", "wichtig"]


# ---------------------------------------------------------------------------
# Validierungs-Tests (Security Fix: Längen-/Mengenbeschränkung)
# ---------------------------------------------------------------------------


def test_create_todo_rejects_too_many_tags(client, household_a, token_a):
    """Mehr als 20 Tags → 422."""
    resp = client.post(
        f"/api/households/{household_a.id}/todos/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": "Zu viele Tags", "tags": [f"tag{i}" for i in range(21)]},
    )
    assert resp.status_code == 422


def test_create_todo_rejects_empty_tag(client, household_a, token_a):
    """Leerer Tag-String → 422."""
    resp = client.post(
        f"/api/households/{household_a.id}/todos/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": "Leerer Tag", "tags": ["ok", ""]},
    )
    assert resp.status_code == 422


def test_create_todo_rejects_whitespace_only_tag(client, household_a, token_a):
    """Tag nur aus Leerzeichen → 422."""
    resp = client.post(
        f"/api/households/{household_a.id}/todos/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": "Blank Tag", "tags": ["  "]},
    )
    assert resp.status_code == 422


def test_create_todo_rejects_tag_over_50_chars(client, household_a, token_a):
    """Tag mit 51+ Zeichen → 422."""
    long_tag = "a" * 51
    resp = client.post(
        f"/api/households/{household_a.id}/todos/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": "Langer Tag", "tags": [long_tag]},
    )
    assert resp.status_code == 422


def test_create_todo_accepts_tag_with_50_chars(client, household_a, token_a):
    """Tag mit exakt 50 Zeichen → OK."""
    tag_50 = "a" * 50
    resp = client.post(
        f"/api/households/{household_a.id}/todos/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": "Grenz-Tag", "tags": [tag_50]},
    )
    assert resp.status_code == 201
    assert resp.json()["tags"] == [tag_50]


def test_create_todo_accepts_20_tags(client, household_a, token_a):
    """Exakt 20 Tags → OK."""
    tags = [f"tag{i}" for i in range(20)]
    resp = client.post(
        f"/api/households/{household_a.id}/todos/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": "Max Tags", "tags": tags},
    )
    assert resp.status_code == 201
    assert len(resp.json()["tags"]) == 20


def test_create_todo_strips_tag_whitespace(client, household_a, token_a):
    """Tags mit Whitespace → werden getrimmt."""
    resp = client.post(
        f"/api/households/{household_a.id}/todos/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": "Trim Test", "tags": ["  küche  ", "bad"]},
    )
    assert resp.status_code == 201
    assert resp.json()["tags"] == ["küche", "bad"]


def test_update_todo_rejects_too_many_tags(client, household_a, token_a):
    """PATCH mit 21+ Tags → 422."""
    create_resp = client.post(
        f"/api/households/{household_a.id}/todos/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": "Update-Limit"},
    )
    todo_id = create_resp.json()["id"]

    resp = client.patch(
        f"/api/households/{household_a.id}/todos/{todo_id}",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"tags": [f"tag{i}" for i in range(21)]},
    )
    assert resp.status_code == 422


def test_update_todo_rejects_empty_tag(client, household_a, token_a):
    """PATCH mit leerem Tag → 422."""
    create_resp = client.post(
        f"/api/households/{household_a.id}/todos/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": "Update-Empty"},
    )
    todo_id = create_resp.json()["id"]

    resp = client.patch(
        f"/api/households/{household_a.id}/todos/{todo_id}",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"tags": ["ok", ""]},
    )
    assert resp.status_code == 422


def test_update_todo_rejects_long_tag(client, household_a, token_a):
    """PATCH mit Tag > 50 Zeichen → 422."""
    create_resp = client.post(
        f"/api/households/{household_a.id}/todos/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": "Update-Long"},
    )
    todo_id = create_resp.json()["id"]

    resp = client.patch(
        f"/api/households/{household_a.id}/todos/{todo_id}",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"tags": ["a" * 51]},
    )
    assert resp.status_code == 422
