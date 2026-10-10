"""Finanz-Integrität: Versionen/If-Match, Soft Delete + Verlauf, Wiederherstellen,
Settlement-Idempotenz/Plausibilität, Grenzen, Paginierung, Rechnungs-Nachbuchung.

CASA-01 (sequenzieller Teil, Nebenläufigkeit: tests/pg/test_pg_finance.py), CASA-02/03/08/09/
23/36, PD-F1/F2/F3/F4/F5/F7. Siehe docs/qa/FULL_LOGIC_AUDIT.md.
"""

import uuid
from datetime import date, timedelta

from app.models import Expense, HouseholdMember, Settlement
from app.services.finance_rules import add_months, first_of_month
from app.services.household_time import household_today


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _url(household, path=""):
    return f"/api/households/{household.id}{path}"


def _create_expense(client, household, token, payer, participants, amount=1000, **extra):
    body = {
        "description": extra.pop("description", "Einkauf"),
        "amount_rappen": amount,
        "paid_by_user_id": str(payer.id),
        "split_type": "even",
        "participant_ids": [str(p.id) for p in participants],
        **extra,
    }
    resp = client.post(_url(household, "/expenses/"), json=body, headers=_h(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _saldi(client, household, token):
    data = client.get(_url(household, "/expenses/balances"), headers=_h(token)).json()
    return {b["user_id"]: b["saldo_rappen"] for b in data["balances"]}


def _today(db, household):
    return household_today(db, household)


# ---------------------------------------------------------------------------
# PD-F7 / CASA-09: Version + If-Match
# ---------------------------------------------------------------------------


def test_expense_has_version_and_attribution(client, household_a, token_a, token_a2, user_a, user_a2):
    exp = _create_expense(client, household_a, token_a, user_a, [user_a, user_a2])
    assert exp["version"] == 1
    assert exp["created_by_user_id"] == str(user_a.id)
    assert exp["updated_by_user_id"] is None
    assert exp["deleted_at"] is None

    resp = client.patch(
        _url(household_a, f"/expenses/{exp['id']}"),
        json={"description": "Wocheneinkauf"},
        headers={**_h(token_a2), "If-Match": '"1"'},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 2
    assert resp.json()["updated_by_user_id"] == str(user_a2.id)


def test_stale_full_patch_rejected_with_409(client, household_a, token_a, token_a2, user_a, user_a2):
    """CASA-09 (scenario 5): Ben korrigiert den Betrag; Annas älterer Dialog überschreibt ihn nicht."""
    exp = _create_expense(client, household_a, token_a, user_a, [user_a, user_a2], amount=10000)
    url = _url(household_a, f"/expenses/{exp['id']}")

    ben = client.patch(url, json={"amount_rappen": 25000}, headers={**_h(token_a2), "If-Match": "1"})
    assert ben.status_code == 200

    anna = client.patch(
        url,
        json={"description": "Pizza", "amount_rappen": 10000},
        headers={**_h(token_a), "If-Match": "1"},
    )
    assert anna.status_code == 409
    detail = anna.json()["detail"]
    assert detail["code"] == "EXPENSE_VERSION_CONFLICT"
    assert detail["current"]["amount_rappen"] == 25000
    assert detail["current"]["version"] == 2

    current = client.get(url, headers=_h(token_a)).json()
    assert current["amount_rappen"] == 25000
    assert sum(s["amount_rappen"] for s in current["shares"]) == 25000


def test_share_only_change_bumps_version(client, household_a, token_a, user_a, user_a2):
    exp = _create_expense(client, household_a, token_a, user_a, [user_a, user_a2])
    resp = client.patch(
        _url(household_a, f"/expenses/{exp['id']}"),
        json={"participant_ids": [str(user_a.id)]},
        headers=_h(token_a),
    )
    assert resp.json()["version"] == 2


def test_category_can_be_cleared(client, household_a, token_a, user_a, user_a2):
    """CASA-38: explizites null leert die Kategorie."""
    exp = _create_expense(client, household_a, token_a, user_a, [user_a], category="groceries")
    resp = client.patch(
        _url(household_a, f"/expenses/{exp['id']}"), json={"category": None}, headers=_h(token_a)
    )
    assert resp.status_code == 200
    assert resp.json()["category"] is None


# ---------------------------------------------------------------------------
# PD-F1 / CASA-02: Soft Delete, Verlauf, Salden
# ---------------------------------------------------------------------------


def test_soft_delete_hides_from_list_and_balances_but_keeps_history(
    client, db, household_a, token_a, token_a2, user_a, user_a2
):
    exp = _create_expense(client, household_a, token_a, user_a, [user_a, user_a2], amount=2000)
    assert _saldi(client, household_a, token_a)[str(user_a.id)] == 1000

    resp = client.delete(_url(household_a, f"/expenses/{exp['id']}"), headers=_h(token_a2))
    assert resp.status_code == 204

    listed = client.get(_url(household_a, "/expenses/"), headers=_h(token_a)).json()
    assert [e["id"] for e in listed] == []
    assert _saldi(client, household_a, token_a)[str(user_a.id)] == 0

    history = client.get(_url(household_a, "/expenses/?deleted=true"), headers=_h(token_a)).json()
    assert len(history) == 1
    assert history[0]["deleted_by_user_id"] == str(user_a2.id)
    assert history[0]["deleted_at"] is not None
    # Anteile bleiben für das Wiederherstellen erhalten
    assert sum(s["amount_rappen"] for s in history[0]["shares"]) == 2000

    # Zeile existiert weiterhin (Soft Delete)
    db.expire_all()
    assert db.get(Expense, uuid.UUID(exp["id"])).deleted_at is not None


def test_deleted_expense_excluded_from_finance_summary(client, household_a, token_a, user_a, user_a2):
    exp = _create_expense(client, household_a, token_a, user_a, [user_a, user_a2], amount=4000, category="groceries")
    client.delete(_url(household_a, f"/expenses/{exp['id']}"), headers=_h(token_a))
    summary = client.get(_url(household_a, "/finance-summary"), headers=_h(token_a)).json()
    assert summary["total_spent_rappen"] == 0
    assert summary["by_category"] == []


def test_delete_is_idempotent_and_patch_on_deleted_is_409(client, household_a, token_a, user_a, user_a2):
    exp = _create_expense(client, household_a, token_a, user_a, [user_a, user_a2])
    url = _url(household_a, f"/expenses/{exp['id']}")
    assert client.delete(url, headers=_h(token_a)).status_code == 204
    assert client.delete(url, headers=_h(token_a)).status_code == 204
    resp = client.patch(url, json={"description": "x"}, headers=_h(token_a))
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "EXPENSE_DELETED"


def test_delete_emits_deleted_by(client, household_a, token_a2, token_a, user_a, user_a2, _mock_socket_emit):
    exp = _create_expense(client, household_a, token_a, user_a, [user_a, user_a2])
    _mock_socket_emit.reset_mock()
    client.delete(_url(household_a, f"/expenses/{exp['id']}"), headers=_h(token_a2))
    (_, event, data), _ = _mock_socket_emit.call_args
    assert event == "expense_deleted"
    assert data["deleted_by_user_id"] == str(user_a2.id)


def test_before_last_settlement_flag(client, db, household_a, token_a, user_a, user_a2):
    """PD-F2: Ausgaben auf/vor dem letzten Ausgleich zwischen Beteiligten werden markiert."""
    today = _today(db, household_a)
    old = _create_expense(
        client, household_a, token_a, user_a, [user_a, user_a2], amount=2000,
        expense_date=(today - timedelta(days=3)).isoformat(),
    )
    assert old["before_last_settlement"] is False

    resp = client.post(
        _url(household_a, "/settlements/"),
        json={"from_user_id": str(user_a2.id), "to_user_id": str(user_a.id), "amount_rappen": 1000,
              "settled_date": (today - timedelta(days=1)).isoformat()},
        headers=_h(token_a),
    )
    assert resp.status_code == 201

    new = _create_expense(client, household_a, token_a, user_a, [user_a, user_a2], amount=500)
    by_id = {e["id"]: e for e in client.get(_url(household_a, "/expenses/"), headers=_h(token_a)).json()}
    assert by_id[old["id"]]["before_last_settlement"] is True
    assert by_id[new["id"]]["before_last_settlement"] is False
    # Ausgabe nur einer Person: kein Paar betroffen
    solo = _create_expense(
        client, household_a, token_a, user_a, [user_a], amount=500,
        expense_date=(today - timedelta(days=5)).isoformat(),
    )
    assert solo["before_last_settlement"] is False


def test_settled_history_change_toward_ex_member_is_visible(client, db, household_a, token_a, user_a, user_a2):
    """CASA-02 (J1): Gelöschte Ausgabe eines Ex-Mitglieds bleibt im Verlauf sichtbar und
    lässt sich wiederherstellen — die Forderung geht nicht still verloren."""
    exp = _create_expense(client, household_a, token_a, user_a2, [user_a, user_a2], amount=3000)
    db.query(HouseholdMember).filter_by(household_id=household_a.id, user_id=user_a2.id).delete()
    db.commit()

    assert client.delete(_url(household_a, f"/expenses/{exp['id']}"), headers=_h(token_a)).status_code == 204
    history = client.get(_url(household_a, "/expenses/?deleted=true"), headers=_h(token_a)).json()
    assert history[0]["paid_by_user_id"] == str(user_a2.id)
    assert history[0]["deleted_by_user_id"] == str(user_a.id)

    # CASA-03: Wiederherstellen trotz Ex-Mitglied (kein USERS_NOT_IN_HOUSEHOLD)
    restored = client.post(_url(household_a, f"/expenses/{exp['id']}/restore"), headers=_h(token_a))
    assert restored.status_code == 200, restored.text
    assert {s["user_id"] for s in restored.json()["shares"]} == {str(user_a.id), str(user_a2.id)}
    assert _saldi(client, household_a, token_a)[str(user_a2.id)] == 1500


# ---------------------------------------------------------------------------
# CASA-03: Wiederherstellen gebuchter Rechnungen
# ---------------------------------------------------------------------------


def _book(client, household, bill, token, **body):
    return client.post(_url(household, f"/recurring-bills/{bill.id}/book"), json=body or None, headers=_h(token))


def _bill_booked(client, household, bill, token, month=None):
    q = f"?month={month.isoformat()}" if month else ""
    summary = client.get(_url(household, f"/finance-summary{q}"), headers=_h(token)).json()
    return next(b for b in summary["pending_bills"] if b["id"] == str(bill.id))["is_booked_this_month"]


def test_restore_booked_expense_keeps_bill_link(client, household_a, token_a, user_a, user_a2, bill_a):
    booked = _book(client, household_a, bill_a, token_a)
    assert booked.status_code == 201
    exp_id = booked.json()["id"]

    client.delete(_url(household_a, f"/expenses/{exp_id}"), headers=_h(token_a))
    assert _bill_booked(client, household_a, bill_a, token_a) is False

    restored = client.post(_url(household_a, f"/expenses/{exp_id}/restore"), headers=_h(token_a))
    assert restored.status_code == 200
    data = restored.json()
    assert data["recurring_bill_id"] == str(bill_a.id)
    assert data["booked_month"] == booked.json()["booked_month"]
    assert data["deleted_at"] is None
    assert _bill_booked(client, household_a, bill_a, token_a) is True

    # Kein zweites Buchen im selben Monat
    again = _book(client, household_a, bill_a, token_a)
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "BILL_ALREADY_BOOKED"


def test_deleted_booking_frees_month_and_blocks_restore_after_rebook(
    client, household_a, token_a, user_a, bill_a
):
    """Gelöschte Buchung gibt den Monat frei; nach Neubuchung ist Wiederherstellen 409."""
    first = _book(client, household_a, bill_a, token_a).json()
    client.delete(_url(household_a, f"/expenses/{first['id']}"), headers=_h(token_a))

    rebook = _book(client, household_a, bill_a, token_a)
    assert rebook.status_code == 201

    restore = client.post(_url(household_a, f"/expenses/{first['id']}/restore"), headers=_h(token_a))
    assert restore.status_code == 409
    assert restore.json()["detail"]["code"] == "BILL_ALREADY_BOOKED"

    listed = client.get(_url(household_a, "/expenses/"), headers=_h(token_a)).json()
    assert [e["id"] for e in listed if e["recurring_bill_id"] == str(bill_a.id)] == [rebook.json()["id"]]


def test_restore_is_idempotent(client, household_a, token_a, user_a, user_a2):
    exp = _create_expense(client, household_a, token_a, user_a, [user_a, user_a2])
    url = _url(household_a, f"/expenses/{exp['id']}")
    client.delete(url, headers=_h(token_a))
    assert client.post(url + "/restore", headers=_h(token_a)).status_code == 200
    second = client.post(url + "/restore", headers=_h(token_a))
    assert second.status_code == 200
    assert len(client.get(_url(household_a, "/expenses/"), headers=_h(token_a)).json()) == 1


def test_restore_unknown_expense_404(client, household_a, token_a):
    resp = client.post(_url(household_a, f"/expenses/{uuid.uuid4()}/restore"), headers=_h(token_a))
    assert resp.status_code == 404


def test_restore_foreign_household_403(client, household_b, token_a, expense_b):
    resp = client.post(_url(household_b, f"/expenses/{expense_b.id}/restore"), headers=_h(token_a))
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PD-F4 / PD-F5: Rechnungen
# ---------------------------------------------------------------------------


def test_retro_booking_past_month(client, db, household_a, token_a, user_a, bill_a):
    current = first_of_month(_today(db, household_a))
    last_month = add_months(current, -1)
    resp = _book(client, household_a, bill_a, token_a, month=last_month.isoformat())
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["booked_month"] == last_month.isoformat()
    assert data["expense_date"] == date(last_month.year, last_month.month, bill_a.day_of_month).isoformat()
    assert _bill_booked(client, household_a, bill_a, token_a, month=last_month) is True
    assert _bill_booked(client, household_a, bill_a, token_a) is False

    # Gleicher Monat nochmals → 409 (Eindeutigkeit bleibt)
    assert _book(client, household_a, bill_a, token_a, month=last_month.isoformat()).status_code == 409
    # Aktueller Monat weiterhin buchbar
    assert _book(client, household_a, bill_a, token_a).status_code == 201


def test_retro_booking_limits(client, db, household_a, token_a, user_a, bill_a):
    current = first_of_month(_today(db, household_a))
    future = _book(client, household_a, bill_a, token_a, month=add_months(current, 1).isoformat())
    assert future.status_code == 422
    assert future.json()["detail"]["code"] == "BILL_MONTH_OUT_OF_RANGE"
    too_old = _book(client, household_a, bill_a, token_a, month=add_months(current, -13).isoformat())
    assert too_old.json()["detail"]["code"] == "BILL_MONTH_OUT_OF_RANGE"
    not_first = _book(client, household_a, bill_a, token_a, month=current.replace(day=15).isoformat())
    assert not_first.json()["detail"]["code"] == "INVALID_MONTH"
    oldest_ok = _book(client, household_a, bill_a, token_a, month=add_months(current, -12).isoformat())
    assert oldest_ok.status_code == 201


def test_bill_custom_split_rejected(client, household_a, token_a, bill_a):
    resp = client.post(
        _url(household_a, "/recurring-bills/"),
        json={"name": "Strom", "amount_rappen": 1000, "day_of_month": 5, "split_type": "custom"},
        headers=_h(token_a),
    )
    assert resp.status_code == 422
    resp = client.patch(
        _url(household_a, f"/recurring-bills/{bill_a.id}"), json={"split_type": "custom"}, headers=_h(token_a)
    )
    assert resp.status_code == 422


def test_bill_booked_event_carries_month(client, household_a, token_a, user_a, bill_a, _mock_socket_emit):
    booked = _book(client, household_a, bill_a, token_a).json()
    events = {c.args[1]: c.args[2] for c in _mock_socket_emit.call_args_list}
    assert events["recurring_bill_booked"]["booked_month"] == booked["booked_month"]


# ---------------------------------------------------------------------------
# PD-F3 / CASA-08: Settlements
# ---------------------------------------------------------------------------


def _settle(client, household, token, frm, to, amount, **extra):
    return client.post(
        _url(household, "/settlements/"),
        json={"from_user_id": str(frm.id), "to_user_id": str(to.id), "amount_rappen": amount, **extra},
        headers=_h(token),
    )


def test_settlement_client_id_is_idempotent(client, db, household_a, token_a, token_a2, user_a, user_a2):
    _create_expense(client, household_a, token_a, user_a, [user_a, user_a2], amount=5000)
    sid = str(uuid.uuid4())
    first = _settle(client, household_a, token_a2, user_a2, user_a, 2500, id=sid)
    assert first.status_code == 201
    assert first.json()["id"] == sid
    assert first.json()["warnings"] == []
    retry = _settle(client, household_a, token_a2, user_a2, user_a, 2500, id=sid)
    assert retry.status_code == 200
    assert retry.json()["id"] == sid
    assert db.query(Settlement).filter_by(household_id=household_a.id).count() == 1
    assert _saldi(client, household_a, token_a)[str(user_a.id)] == 0


def test_settlement_check_warns_on_duplicate_and_overpayment(
    client, household_a, token_a, token_a2, user_a, user_a2
):
    _create_expense(client, household_a, token_a, user_a, [user_a, user_a2], amount=5000)
    body = {"from_user_id": str(user_a2.id), "to_user_id": str(user_a.id), "amount_rappen": 2500}
    check = client.post(_url(household_a, "/settlements/check"), json=body, headers=_h(token_a2)).json()
    assert check == {"warnings": [], "open_debt_rappen": 2500}

    assert _settle(client, household_a, token_a2, user_a2, user_a, 2500).status_code == 201
    # Gläubiger erfasst dieselbe Zahlung: Duplikat + mehr als die (jetzt 0) offene Schuld
    check = client.post(_url(household_a, "/settlements/check"), json=body, headers=_h(token_a)).json()
    assert set(check["warnings"]) == {"DUPLICATE_RECENT", "EXCEEDS_OPEN_DEBT"}
    assert check["open_debt_rappen"] == 0

    # Warnen, nicht ablehnen: gespeichert wird trotzdem, die Antwort trägt die Warnung
    second = _settle(client, household_a, token_a, user_a2, user_a, 2500)
    assert second.status_code == 201
    assert "DUPLICATE_RECENT" in second.json()["warnings"]


def test_settlement_against_debt_direction_warns(client, household_a, token_a, user_a, user_a2):
    _create_expense(client, household_a, token_a, user_a, [user_a, user_a2], amount=5000)
    resp = client.post(
        _url(household_a, "/settlements/check"),
        json={"from_user_id": str(user_a.id), "to_user_id": str(user_a2.id), "amount_rappen": 100},
        headers=_h(token_a),
    ).json()
    assert resp["warnings"] == ["EXCEEDS_OPEN_DEBT"]


def test_settlement_soft_delete_and_restore(client, household_a, token_a, token_a2, user_a, user_a2):
    _create_expense(client, household_a, token_a, user_a, [user_a, user_a2], amount=5000)
    s = _settle(client, household_a, token_a2, user_a2, user_a, 2500).json()
    assert s["created_by_user_id"] == str(user_a2.id)
    assert client.delete(_url(household_a, f"/settlements/{s['id']}"), headers=_h(token_a)).status_code == 204
    assert _saldi(client, household_a, token_a)[str(user_a.id)] == 2500
    assert client.get(_url(household_a, "/settlements/"), headers=_h(token_a)).json() == []
    history = client.get(_url(household_a, "/settlements/?deleted=true"), headers=_h(token_a)).json()
    assert history[0]["deleted_by_user_id"] == str(user_a.id)

    restored = client.post(_url(household_a, f"/settlements/{s['id']}/restore"), headers=_h(token_a))
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None
    assert _saldi(client, household_a, token_a)[str(user_a.id)] == 0


# ---------------------------------------------------------------------------
# CASA-36: Grenzen
# ---------------------------------------------------------------------------


def test_amount_upper_bound(client, household_a, token_a, user_a, bill_a):
    body = {"description": "x", "amount_rappen": 10**9 + 1, "paid_by_user_id": str(user_a.id), "split_type": "even"}
    assert client.post(_url(household_a, "/expenses/"), json=body, headers=_h(token_a)).status_code == 422
    body["amount_rappen"] = 2**31
    assert client.post(_url(household_a, "/expenses/"), json=body, headers=_h(token_a)).status_code == 422
    body["amount_rappen"] = 10**9
    assert client.post(_url(household_a, "/expenses/"), json=body, headers=_h(token_a)).status_code == 201
    resp = _settle(client, household_a, token_a, user_a, user_a, 10**9 + 1)
    assert resp.status_code == 422
    resp = client.put(_url(household_a, "/budget"), json={"month": "2026-10-01", "amount_rappen": 2**31}, headers=_h(token_a))
    assert resp.status_code == 422
    resp = client.patch(_url(household_a, f"/recurring-bills/{bill_a.id}"), json={"amount_rappen": 2**31}, headers=_h(token_a))
    assert resp.status_code == 422


def test_date_bounds(client, db, household_a, token_a, user_a, user_a2):
    for bad in ("0001-01-01", "9999-12-31"):
        resp = client.post(
            _url(household_a, "/expenses/"),
            json={"description": "x", "amount_rappen": 100, "paid_by_user_id": str(user_a.id),
                  "split_type": "even", "expense_date": bad},
            headers=_h(token_a),
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "DATE_OUT_OF_RANGE"
        resp = _settle(client, household_a, token_a, user_a2, user_a, 100, settled_date=bad)
        assert resp.json()["detail"]["code"] == "DATE_OUT_OF_RANGE"

    exp = _create_expense(client, household_a, token_a, user_a, [user_a])
    resp = client.patch(
        _url(household_a, f"/expenses/{exp['id']}"), json={"expense_date": "9999-12-31"}, headers=_h(token_a)
    )
    assert resp.json()["detail"]["code"] == "DATE_OUT_OF_RANGE"
    ok = (_today(db, household_a) - timedelta(days=365 * 9)).isoformat()
    resp = client.patch(_url(household_a, f"/expenses/{exp['id']}"), json={"expense_date": ok}, headers=_h(token_a))
    assert resp.status_code == 200


def test_finance_summary_month_validation(client, household_a, token_a):
    for bad in ("9999-12-01", "0001-01-01", "2026-10-15"):
        resp = client.get(_url(household_a, f"/finance-summary?month={bad}"), headers=_h(token_a))
        assert resp.status_code == 422, bad
        assert resp.json()["detail"]["code"] == "INVALID_MONTH"
    for path in ("/budget?month=9999-12-01",):
        assert client.get(_url(household_a, path), headers=_h(token_a)).status_code == 422
    resp = client.put(_url(household_a, "/budget"), json={"month": "9999-12-01", "amount_rappen": 100}, headers=_h(token_a))
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# CASA-23: Paginierung / Monatsfilter
# ---------------------------------------------------------------------------


def test_expense_pagination_and_month_filter(client, db, household_a, token_a, user_a):
    today = _today(db, household_a)
    current = first_of_month(today)
    previous = add_months(current, -1)
    ids = []
    for i in range(5):
        d = current if i < 3 else previous
        ids.append(_create_expense(client, household_a, token_a, user_a, [user_a], amount=100 + i,
                                   expense_date=d.isoformat())["id"])

    page1 = client.get(_url(household_a, "/expenses/?limit=2&offset=0"), headers=_h(token_a)).json()
    page2 = client.get(_url(household_a, "/expenses/?limit=2&offset=2"), headers=_h(token_a)).json()
    page3 = client.get(_url(household_a, "/expenses/?limit=2&offset=4"), headers=_h(token_a)).json()
    seen = [e["id"] for e in page1 + page2 + page3]
    assert sorted(seen) == sorted(ids) and len(set(seen)) == 5

    prev = client.get(_url(household_a, f"/expenses/?month={previous.isoformat()}"), headers=_h(token_a)).json()
    assert sorted(e["id"] for e in prev) == sorted(ids[3:])
    bad = client.get(_url(household_a, "/expenses/?month=2026-10-02"), headers=_h(token_a))
    assert bad.status_code == 422


def test_me_exposes_household_timezone(client, household_a, token_a, user_a):
    """CASA-39: Clients rechnen "heute" in Haushaltszeit — /me liefert die Zeitzone."""
    me = client.get("/api/auth/me", headers=_h(token_a)).json()
    hh = next(h for h in me["households"] if h["id"] == str(household_a.id))
    assert hh["timezone"] == household_a.timezone


def test_settlement_pagination(client, household_a, token_a, user_a, user_a2):
    for i in range(3):
        _settle(client, household_a, token_a, user_a2, user_a, 100 + i)
    page = client.get(_url(household_a, "/settlements/?limit=2"), headers=_h(token_a)).json()
    rest = client.get(_url(household_a, "/settlements/?limit=2&offset=2"), headers=_h(token_a)).json()
    assert len(page) == 2 and len(rest) == 1
