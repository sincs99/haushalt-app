"""Mitgliedschaft ändern: Beitreten, Verlassen, Entfernen (CASA-10/22, PD-H1/H3).

Alle Abläufe sperren zuerst die ``households``-Zeile (``lock_household``) und prüfen
erst danach — parallele Joins/Leaves/Removes desselben Haushalts laufen nacheinander.
Invarianten nach jedem Commit:

- Hat ein Haushalt Mitglieder, gibt es mindestens einen Admin (sonst wird das
  dienstälteste Mitglied befördert — auch als Reparatur bei jeder Änderung).
- Ein Haushalt ohne Mitglieder wird gelöscht (CASCADE), seine Dateien danach auch.
"""

import uuid

from sqlalchemy.orm import Session

from app.models import HouseholdMember


def locked_membership(db: Session, household_id: uuid.UUID, user_id: uuid.UUID) -> HouseholdMember | None:
    """Mitgliedschaft frisch aus der DB (nach ``lock_household`` aufrufen).

    Die Dependency ``verify_household_access`` hat die Zeile VOR der Sperre gelesen —
    sie kann inzwischen gelöscht oder (Beförderung) geändert sein.
    """
    return (
        db.query(HouseholdMember)
        .filter_by(household_id=household_id, user_id=user_id)
        .populate_existing()
        .first()
    )


def ensure_admin(db: Session, household_id: uuid.UUID) -> HouseholdMember | None:
    """Befördert das dienstälteste Mitglied, wenn der Haushalt Mitglieder, aber keinen Admin hat.

    Reihenfolge: ``joined_at`` aufsteigend, dann ``user_id`` (deterministisch).
    Gibt das beförderte Mitglied zurück (None = nichts zu tun).
    """
    members = (
        db.query(HouseholdMember)
        .filter(HouseholdMember.household_id == household_id)
        .populate_existing()
        .all()
    )
    if not members or any(m.role == "admin" for m in members):
        return None
    promoted = min(members, key=lambda m: (m.joined_at, str(m.user_id)))
    promoted.role = "admin"
    db.flush()
    return promoted


def member_count(db: Session, household_id: uuid.UUID) -> int:
    return db.query(HouseholdMember).filter(HouseholdMember.household_id == household_id).count()
