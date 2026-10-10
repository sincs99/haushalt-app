"""Property-Test der Ledger-Invarianten auf PostgreSQL (portiert aus
docs/qa/audit-evidence/finance/pg_props.py).

Zufällige Folgen echter REST-Operationen (Anlegen, Ändern, Löschen/Wiederherstellen,
Ausgleiche, Austritt/Beitritt, Rechnungen buchen). Nach jedem Schritt:
- Σ Anteile == Betrag für jede Ausgabe (auch gelöschte — sie bleiben wiederherstellbar)
- keine negativen Anteile, keine Ausgabe ohne Anteile
- Σ Salden == −unassigned; die Vorschläge gleichen alle Salden aus, mit höchstens n−1 Zahlungen
- kein 5xx
Bewusst wenige Beispiele (CI-Laufzeit); lokal mit HYPOTHESIS_PROFILE o. ä. erhöhen.
"""

import uuid

from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import strategies as st
from sqlalchemy import text

from app.database import SessionLocal
from tests.pg.harness import add_member, auth_headers, create_household


def _check(client, hh, token):
    with SessionLocal() as s:
        rows = s.execute(
            text(
                "SELECT e.id, e.amount_rappen, COALESCE(SUM(sh.amount_rappen), 0), COUNT(sh.id) "
                "FROM expenses e LEFT JOIN expense_shares sh ON sh.expense_id = e.id "
                "WHERE e.household_id = :h GROUP BY e.id"
            ),
            {"h": hh.id},
        ).all()
        negative = s.execute(
            text("SELECT count(*) FROM expense_shares WHERE household_id = :h AND amount_rappen < 0"),
            {"h": hh.id},
        ).scalar()
    for eid, amount, share_sum, n in rows:
        assert share_sum == amount, f"expense {eid}: shares {share_sum} != amount {amount}"
        assert n >= 1, f"expense {eid} without shares"
    assert negative == 0

    b = client.get(hh.url("/expenses/balances"), headers=auth_headers(token)).json()
    saldi = {x["user_id"]: x["saldo_rappen"] for x in b["balances"]}
    assert sum(saldi.values()) == -b["unassigned_rappen"]
    after = dict(saldi)
    for t in b["settlements"]:
        after[t["from_user_id"]] += t["amount_rappen"]
        after[t["to_user_id"]] -= t["amount_rappen"]
    assert all(v == 0 for v in after.values()), after
    nonzero = sum(1 for v in saldi.values() if v)
    assert len(b["settlements"]) <= max(nonzero - 1, 0)


_idx = st.integers(0, 50)
_user = st.integers(0, 4)
_custom = st.lists(st.tuples(_user, st.integers(0, 5000)), min_size=1, max_size=5)

OPS = st.one_of(
    st.tuples(st.just("create_even"), st.integers(1, 10**7), _user, st.lists(_user, max_size=5)),
    st.tuples(st.just("create_custom"), _user, _custom),
    st.tuples(st.just("patch_amount"), _idx, st.integers(1, 10**7)),
    st.tuples(st.just("patch_participants"), _idx, st.lists(_user, max_size=5)),
    st.tuples(st.just("patch_to_custom"), _idx, _custom),
    st.tuples(st.just("patch_to_even"), _idx),
    st.tuples(st.just("patch_payer"), _idx, _user),
    st.tuples(st.just("patch_fullpayload"), _idx),
    st.tuples(st.just("delete"), _idx),
    st.tuples(st.just("restore"), _idx),
    st.tuples(st.just("settle_suggestion"), st.integers(0, 10)),
    st.tuples(st.just("settle_random"), _user, _user, st.integers(1, 10**6)),
    st.tuples(st.just("leave"), st.integers(1, 4)),
    st.tuples(st.just("join")),
    st.tuples(st.just("book"), st.integers(1, 10**6), _user),
)


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=list(HealthCheck),
    phases=[Phase.generate],
    derandomize=True,
)
@given(st.lists(OPS, min_size=1, max_size=20))
def test_ledger_invariants_hold_for_random_operation_sequences(client, pg_url, ops):
    hh = create_household(["A", "B", "C", "D"])
    users = list(hh.user_ids)
    tokens = list(hh.tokens)
    active = [True] * 4
    expenses_url = hh.url("/expenses/")
    live: list[str] = []
    deleted: list[str] = []

    def uid(i):
        return str(users[i % len(users)])

    def actor():
        return next((tokens[i] for i, a in enumerate(active) if a), None)

    for k, amount in enumerate((1001, 77, 333334)):
        r = client.post(
            expenses_url,
            json={
                "description": "seed", "amount_rappen": amount, "paid_by_user_id": uid(k),
                "split_type": "even",
                "participant_ids": [uid(j) for j in range(k + 1, 4)] if k < 2 else None,
            },
            headers=auth_headers(tokens[0]),
        )
        live.append(r.json()["id"])

    for op in ops:
        kind = op[0]
        token = actor()
        if token is None:
            break
        h = auth_headers(token)
        r = None
        if kind == "create_even":
            r = client.post(expenses_url, json={
                "description": "e", "amount_rappen": op[1], "paid_by_user_id": uid(op[2]),
                "split_type": "even", "participant_ids": [uid(i) for i in op[3]] or None,
            }, headers=h)
            if r.status_code == 201:
                live.append(r.json()["id"])
        elif kind == "create_custom":
            r = client.post(expenses_url, json={
                "description": "c", "amount_rappen": max(1, sum(a for _, a in op[2])),
                "paid_by_user_id": uid(op[1]), "split_type": "custom",
                "shares": [{"user_id": uid(i), "amount_rappen": a} for i, a in op[2]],
            }, headers=h)
            if r.status_code == 201:
                live.append(r.json()["id"])
        elif kind == "restore":
            if not deleted:
                continue
            eid = deleted[op[1] % len(deleted)]
            r = client.post(hh.url(f"/expenses/{eid}/restore"), headers=h)
            if r.status_code == 200:
                deleted.remove(eid)
                live.append(eid)
        elif kind.startswith("patch") or kind == "delete":
            if not live:
                continue
            eid = live[op[1] % len(live)]
            url = hh.url(f"/expenses/{eid}")
            if kind == "delete":
                r = client.delete(url, headers=h)
                live.remove(eid)
                deleted.append(eid)
            elif kind == "patch_fullpayload":
                # UI-Stil: aktuellen Stand laden und mit If-Match komplett zurückschreiben
                cur = client.get(url, headers=h).json()
                body = {
                    "description": cur["description"], "amount_rappen": cur["amount_rappen"],
                    "paid_by_user_id": cur["paid_by_user_id"], "expense_date": cur["expense_date"],
                    "split_type": cur["split_type"],
                }
                if cur["split_type"] == "even":
                    body["participant_ids"] = [s["user_id"] for s in cur["shares"]]
                else:
                    body["shares"] = cur["shares"]
                r = client.patch(url, json=body, headers={**h, "If-Match": str(cur["version"])})
                assert r.status_code == 200, ("UI-style full payload edit failed", r.text, body)
            else:
                if kind == "patch_amount":
                    body = {"amount_rappen": op[2]}
                elif kind == "patch_participants":
                    body = {"participant_ids": [uid(i) for i in op[2]]}
                elif kind == "patch_to_custom":
                    body = {
                        "split_type": "custom", "amount_rappen": max(1, sum(a for _, a in op[2])),
                        "shares": [{"user_id": uid(i), "amount_rappen": a} for i, a in op[2]],
                    }
                elif kind == "patch_to_even":
                    body = {"split_type": "even"}
                else:
                    body = {"paid_by_user_id": uid(op[2])}
                r = client.patch(url, json=body, headers=h)
        elif kind == "settle_suggestion":
            suggestions = client.get(hh.url("/expenses/balances"), headers=h).json()["settlements"]
            if not suggestions:
                continue
            s = suggestions[op[1] % len(suggestions)]
            r = client.post(hh.url("/settlements/"), json={
                "id": str(uuid.uuid4()), **{k: s[k] for k in ("from_user_id", "to_user_id", "amount_rappen")},
            }, headers=h)
        elif kind == "settle_random":
            r = client.post(hh.url("/settlements/"), json={
                "from_user_id": uid(op[1]), "to_user_id": uid(op[2]), "amount_rappen": op[3],
            }, headers=h)
        elif kind == "leave":
            i = op[1] % len(users)
            if not active[i] or sum(active) <= 1:
                continue
            r = client.post(hh.url("/leave"), headers=auth_headers(tokens[i]))
            active[i] = False
        elif kind == "join":
            if len(users) >= 6:
                continue
            u, t = add_member(hh, "J")
            users.append(u)
            tokens.append(t)
            active.append(True)
        elif kind == "book":
            b = client.post(hh.url("/recurring-bills/"), json={
                "name": "b", "amount_rappen": op[1], "day_of_month": 5, "paid_by_user_id": uid(op[2]),
            }, headers=h)
            if b.status_code != 201:
                continue
            r = client.post(hh.url(f"/recurring-bills/{b.json()['id']}/book"), headers=h)
            if r.status_code == 201:
                live.append(r.json()["id"])
        if r is not None:
            assert r.status_code < 500, (kind, r.status_code, r.text)
        _check(client, hh, actor())
