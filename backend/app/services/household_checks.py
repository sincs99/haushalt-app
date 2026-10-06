import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.error_codes import ErrorCode, error_detail
from app.models import Expense, ExpenseShare, HouseholdMember, Settlement


def assert_users_in_household(
    db: Session, household_id: uuid.UUID, user_ids: list[uuid.UUID]
) -> None:
    """Prüft, ob alle user_ids Mitglieder des Households sind. Wirft 422 wenn nicht."""
    members = (
        db.query(HouseholdMember.user_id)
        .filter(
            HouseholdMember.household_id == household_id,
            HouseholdMember.user_id.in_(user_ids),
        )
        .all()
    )
    member_ids = {m.user_id for m in members}
    missing = set(user_ids) - member_ids
    if missing:
        raise HTTPException(422, detail=error_detail(ErrorCode.USERS_NOT_IN_HOUSEHOLD, f"Users not in household: {[str(u) for u in missing]}"))


def assert_users_allowed(
    db: Session, household_id: uuid.UUID, user_ids: list[uuid.UUID], already_on_record: set[uuid.UUID]
) -> None:
    """Wie assert_users_in_household, aber Personen, die bereits auf dem Datensatz
    stehen (z.B. Teilnehmer einer bestehenden Ausgabe), dürfen auch Ex-Mitglieder sein.
    Nur neu hinzukommende Personen müssen aktuelle Mitglieder sein.
    """
    new_ids = [uid for uid in user_ids if uid not in already_on_record]
    if new_ids:
        assert_users_in_household(db, household_id, new_ids)


def _ledger_user_ids(db: Session, household_id: uuid.UUID) -> set[uuid.UUID]:
    """Alle User, die im Haushalts-Ledger vorkommen (Zahler, Anteile, Ausgleiche)."""
    payers = db.query(Expense.paid_by_user_id).filter(
        Expense.household_id == household_id, Expense.paid_by_user_id.isnot(None)
    )
    sharers = db.query(ExpenseShare.user_id).filter(ExpenseShare.household_id == household_id)
    senders = db.query(Settlement.from_user_id).filter(Settlement.household_id == household_id)
    receivers = db.query(Settlement.to_user_id).filter(Settlement.household_id == household_id)
    return {row[0] for q in (payers, sharers, senders, receivers) for row in q.all()}


def assert_settlement_parties(
    db: Session, household_id: uuid.UUID, from_user_id: uuid.UUID, to_user_id: uuid.UUID
) -> None:
    """Ausgleich ist auch mit Ex-Mitgliedern möglich, damit deren Schulden begleichbar
    bleiben: Mindestens eine Seite muss aktuelles Mitglied sein, die andere muss
    Mitglied sein oder im Haushalts-Ledger vorkommen.
    """
    parties = {from_user_id, to_user_id}
    members = {
        m.user_id
        for m in db.query(HouseholdMember.user_id).filter(
            HouseholdMember.household_id == household_id,
            HouseholdMember.user_id.in_(parties),
        )
    }
    if not members:
        raise HTTPException(422, detail=error_detail(
            ErrorCode.USERS_NOT_IN_HOUSEHOLD, "At least one party must be a current household member",
        ))
    outsiders = parties - members
    if outsiders - _ledger_user_ids(db, household_id):
        raise HTTPException(422, detail=error_detail(
            ErrorCode.USERS_NOT_IN_HOUSEHOLD, f"Users not in household: {[str(u) for u in outsiders]}",
        ))
