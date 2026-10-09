"""Austritt aus einem Haushalt — gemeinsame Regeln für «Haushalt verlassen» und «Konto löschen».

Geschäftsregeln (siehe routers/households.py):
- Letztes Mitglied → Haushalt wird komplett gelöscht (CASCADE), Dateien auf der Platte mit
- Einziger Admin, aber andere Mitglieder → dienstältestes Mitglied wird Admin
- Expenses/Shares werden NICHT gelöscht (Ehemaliges-Mitglied-Muster)
- rotation_order wird NICHT bereinigt (Scheduler überspringt Ex-Mitglieder)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Household, HouseholdMember
from app.services.storage import LocalStorageService

logger = logging.getLogger(__name__)

_storage = LocalStorageService()


@dataclass(frozen=True)
class LeaveResult:
    household_deleted: bool


def leave(db: Session, membership: HouseholdMember) -> LeaveResult:
    """Entfernt die Mitgliedschaft und committet. Socket-Events verschickt der Aufrufer."""
    household_id = membership.household_id

    all_members = db.query(HouseholdMember).filter(HouseholdMember.household_id == household_id).all()

    if len(all_members) <= 1:
        household = db.get(Household, household_id)
        if household:
            db.delete(household)  # CASCADE löscht members, expenses, etc.
        db.commit()
        # Hochgeladene Dateien (Dokumente, Fotos) mitlöschen — die DB-Einträge
        # verschwinden per CASCADE, die Dateien auf der Platte sonst nie
        try:
            _storage.delete_household(str(household_id))
        except Exception:
            logger.warning("Deleting upload folder of household %s failed", household_id, exc_info=True)
        return LeaveResult(household_deleted=True)

    remaining = [m for m in all_members if m.id != membership.id]
    if membership.role == "admin" and not any(m.role == "admin" for m in remaining):
        # Kein anderer Admin → dienstältestes Mitglied promoten
        # Sortierung: joined_at ASC, dann user_id ASC (deterministischer Tiebreaker)
        promoted = sorted(remaining, key=lambda m: (m.joined_at, str(m.user_id)))[0]
        promoted.role = "admin"

    db.delete(membership)
    db.commit()
    return LeaveResult(household_deleted=False)
