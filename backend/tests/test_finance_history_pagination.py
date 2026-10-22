"""Deleted entries with equal timestamps remain reachable across page boundaries."""

import uuid
from datetime import datetime, timezone

import pytest

from app.models import Expense, ExpenseShare, Settlement


@pytest.mark.parametrize("resource", ["expenses", "settlements"])
def test_deleted_history_pages_have_stable_tie_breaker(
    client, db, household_a, token_a, user_a, user_a2, resource,
):
    deleted_at = datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc)
    ids = [uuid.UUID(int=index) for index in range(1, 52)]
    for entry_id in ids:
        common = dict(
            id=entry_id,
            household_id=household_a.id,
            amount_rappen=100,
            deleted_at=deleted_at,
            deleted_by_user_id=user_a.id,
        )
        if resource == "expenses":
            row = Expense(
                **common, description="Archived expense", paid_by_user_id=user_a.id,
                shares=[ExpenseShare(
                    household_id=household_a.id, user_id=user_a.id, amount_rappen=100,
                )],
            )
        else:
            row = Settlement(**common, from_user_id=user_a2.id, to_user_id=user_a.id)
        db.add(row)
    db.commit()

    actual_ids = []
    for offset, expected_count in [(0, 50), (50, 1), (100, 0)]:
        response = client.get(
            f"/api/households/{household_a.id}/{resource}/",
            params={"deleted": "true", "limit": 50, "offset": offset},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert response.status_code == 200, response.text
        rows = response.json()
        assert len(rows) == expected_count
        actual_ids.extend(row["id"] for row in rows)

    assert actual_ids == [str(entry_id) for entry_id in reversed(ids)]
