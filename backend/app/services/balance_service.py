"""
Balance-Service – Wiederverwendbare Saldo-Berechnung.

Extrahiert aus routers/expenses.py, damit Dashboard und andere Module
dieselbe Logik nutzen können.  Gibt plain dicts zurück (keine Pydantic-Objekte).
"""

import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Expense, ExpenseShare, HouseholdMember, Settlement


# ---------------------------------------------------------------------------
# Interne Hilfsfunktionen
# ---------------------------------------------------------------------------

def _build_balance_maps(
    db: Session, household_id: uuid.UUID
) -> tuple[
    dict[uuid.UUID, int],  # paid_map
    dict[uuid.UUID, int],  # owed_map
    dict[uuid.UUID, int],  # settled_out_map
    dict[uuid.UUID, int],  # settled_in_map
    int,                    # unassigned_rappen
]:
    """Aggregiert paid / owed / settled_out / settled_in pro User."""

    # 1. paid: Summe pro Payer (nur wo paid_by_user_id NOT NULL)
    paid_rows = (
        db.query(Expense.paid_by_user_id, func.sum(Expense.amount_rappen))
        .filter(
            Expense.household_id == household_id,
            Expense.paid_by_user_id.isnot(None),
        )
        .group_by(Expense.paid_by_user_id)
        .all()
    )
    paid_map: dict[uuid.UUID, int] = {row[0]: row[1] for row in paid_rows}

    # 2. owed: Summe pro Share-Inhaber
    owed_rows = (
        db.query(ExpenseShare.user_id, func.sum(ExpenseShare.amount_rappen))
        .filter(ExpenseShare.household_id == household_id)
        .group_by(ExpenseShare.user_id)
        .all()
    )
    owed_map: dict[uuid.UUID, int] = {row[0]: row[1] for row in owed_rows}

    # 3. unassigned: Expenses ohne Payer
    unassigned_result = (
        db.query(func.coalesce(func.sum(Expense.amount_rappen), 0))
        .filter(
            Expense.household_id == household_id,
            Expense.paid_by_user_id.is_(None),
        )
        .scalar()
    )
    unassigned_rappen = int(unassigned_result)

    # 4a. settled_out: Summe pro from_user_id
    settled_out_rows = (
        db.query(Settlement.from_user_id, func.sum(Settlement.amount_rappen))
        .filter(Settlement.household_id == household_id)
        .group_by(Settlement.from_user_id)
        .all()
    )
    settled_out_map: dict[uuid.UUID, int] = {row[0]: row[1] for row in settled_out_rows}

    # 4b. settled_in: Summe pro to_user_id
    settled_in_rows = (
        db.query(Settlement.to_user_id, func.sum(Settlement.amount_rappen))
        .filter(Settlement.household_id == household_id)
        .group_by(Settlement.to_user_id)
        .all()
    )
    settled_in_map: dict[uuid.UUID, int] = {row[0]: row[1] for row in settled_in_rows}

    return paid_map, owed_map, settled_out_map, settled_in_map, unassigned_rappen


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------

def compute_user_saldo(db: Session, household_id: uuid.UUID, user_id: uuid.UUID) -> int:
    """Berechnet den Saldo eines einzelnen Users in Rappen.

    saldo = paid - owed + settled_out - settled_in
    Positiv = User bekommt Geld, Negativ = User schuldet Geld.
    """
    paid_map, owed_map, settled_out_map, settled_in_map, _ = _build_balance_maps(
        db, household_id
    )
    paid = paid_map.get(user_id, 0)
    owed = owed_map.get(user_id, 0)
    s_out = settled_out_map.get(user_id, 0)
    s_in = settled_in_map.get(user_id, 0)
    return paid - owed + s_out - s_in


def compute_all_balances(db: Session, household_id: uuid.UUID) -> dict:
    """Berechnet alle Balances + Settlements für ein Household.

    Gibt dict zurück mit keys: balances, settlements, unassigned_rappen.
    balances ist eine Liste von dicts mit user_id, paid_rappen, owed_rappen,
    settled_out_rappen, settled_in_rappen, saldo_rappen.
    settlements ist eine Liste von dicts mit from_user_id, to_user_id, amount_rappen.
    """
    from app.routers.expenses import compute_settlements

    paid_map, owed_map, settled_out_map, settled_in_map, unassigned_rappen = (
        _build_balance_maps(db, household_id)
    )

    # User-Menge: VEREINIGUNG aus aktuellen Mitgliedern + Payern + Share-Inhabern + Settlement-Beteiligte
    member_rows = (
        db.query(HouseholdMember.user_id)
        .filter(HouseholdMember.household_id == household_id)
        .all()
    )
    all_user_ids = (
        {m.user_id for m in member_rows}
        | set(paid_map.keys())
        | set(owed_map.keys())
        | set(settled_out_map.keys())
        | set(settled_in_map.keys())
    )

    # BalanceEntries berechnen
    balances = []
    saldi: dict[uuid.UUID, int] = {}
    for uid in sorted(all_user_ids, key=str):  # deterministisch
        paid = paid_map.get(uid, 0)
        owed = owed_map.get(uid, 0)
        s_out = settled_out_map.get(uid, 0)
        s_in = settled_in_map.get(uid, 0)
        saldo = paid - owed + s_out - s_in
        saldi[uid] = saldo
        balances.append({
            "user_id": uid,
            "paid_rappen": paid,
            "owed_rappen": owed,
            "settled_out_rappen": s_out,
            "settled_in_rappen": s_in,
            "saldo_rappen": saldo,
        })

    # Settlements berechnen
    settlements = compute_settlements(saldi)

    return {
        "balances": balances,
        "settlements": settlements,
        "unassigned_rappen": unassigned_rappen,
    }
