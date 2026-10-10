"""Dashboard zeigt heute fällige UND überfällige Ämtli wie Badge/Widget (CASA-43, PD-C2)."""

from datetime import timedelta

from app.models import Chore, ChoreAssignment
from app.services.chore_scheduler import today_in_tz


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _chore(db, household, user, title, *, active=True):
    today = today_in_tz(household.timezone)
    chore = Chore(
        household_id=household.id,
        title=title,
        recurrence="weekly",
        weekday=today.weekday(),
        rotation_order=[str(user.id)],
        anchor_date=today - timedelta(days=30),
        active=active,
    )
    db.add(chore)
    db.commit()
    return chore


def _assignment(db, household, chore, user, days_ago, *, done=False):
    from datetime import datetime, timezone

    today = today_in_tz(household.timezone)
    a = ChoreAssignment(
        household_id=household.id,
        chore_id=chore.id,
        assigned_user_id=user.id,
        due_date=today - timedelta(days=days_ago),
        completed_at=datetime.now(timezone.utc) if done else None,
    )
    db.add(a)
    db.commit()
    return a


def test_dashboard_lists_today_and_overdue_chores_like_badge(client, db, household_a, token_a, user_a):
    bad = _chore(db, household_a, user_a, "Bad")
    kueche = _chore(db, household_a, user_a, "Küche")
    paused = _chore(db, household_a, user_a, "Pausiert", active=False)
    today_item = _assignment(db, household_a, bad, user_a, 0)
    overdue_item = _assignment(db, household_a, kueche, user_a, 3)
    _assignment(db, household_a, bad, user_a, 7, done=True)  # erledigt
    _assignment(db, household_a, kueche, user_a, 20)  # ausserhalb des Rückblicks
    _assignment(db, household_a, paused, user_a, 2)  # pausiertes Ämtli

    dash = client.get(f"/api/households/{household_a.id}/dashboard", headers=_auth(token_a)).json()
    items = dash["chores"]["items"]
    assert [i["id"] for i in items] == [str(overdue_item.id), str(today_item.id)]
    assert [i["is_overdue"] for i in items] == [True, False]
    assert items[1]["due_date"] == today_in_tz(household_a.timezone).isoformat()
    assert dash["chores"]["overdue_count"] == 1

    # Badge zählt dieselben Ämtli (keine Todos/Pflege in diesem Haushalt)
    badge = client.get(f"/api/households/{household_a.id}/dashboard/badge", headers=_auth(token_a)).json()
    assert badge["count"] == len(items)


def test_unused_tasks_endpoint_removed(client, household_a, token_a):
    r = client.get(f"/api/households/{household_a.id}/tasks", headers=_auth(token_a))
    assert r.status_code == 404
