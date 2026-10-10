"""Mitgliedschaft ändern: Beitreten, Verlassen, Entfernen (CASA-10/22, PD-H1/H3).

Alle Abläufe sperren zuerst die ``households``-Zeile (``lock_household``) und prüfen
erst danach — parallele Joins/Leaves/Removes desselben Haushalts laufen nacheinander.
Invarianten nach jedem Commit:

- Hat ein Haushalt Mitglieder, gibt es mindestens einen Admin (sonst wird das
  dienstälteste Mitglied befördert — auch als Reparatur bei jeder Änderung).
- Ein Haushalt ohne Mitglieder wird gelöscht (CASCADE), seine Dateien danach auch.

Beim Verlassen/Entfernen werden offene Zuständigkeiten der Person im selben Commit
"freigegeben" (PD-H1), siehe ``release_departing_member``.
"""

import uuid
from dataclasses import dataclass, field

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.error_codes import ErrorCode, error_detail
from app.models import (
    Calendar,
    Chore,
    ChoreAssignment,
    EventPoll,
    EventPollVote,
    Household,
    HouseholdMember,
    RecurringBill,
    ShoppingItem,
    Todo,
    WidgetToken,
)
from app.services.invite_code import (
    find_household_by_invite_code,
    generate_unique_invite_code,
    is_invite_code_expired,
    new_invite_code_expiry,
)
from app.services.locking import lock_household


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


# Default-Kalender jedes neuen Haushalts, damit Events sofort möglich sind
DEFAULT_CALENDAR_NAME = "Allgemein"
DEFAULT_CALENDAR_COLOR = "#5B8DEF"


def create_household_with_admin(db: Session, name: str, user_id: uuid.UUID) -> tuple[Household, HouseholdMember]:
    """Legt einen neuen Haushalt mit ``user_id`` als Admin an. Kein Commit.

    Einziger Weg für POST /households/ und die Registrierung mit Haushaltsnamen:
    eindeutiger Einladungscode mit Ablaufdatum, Admin-Mitgliedschaft, Default-Kalender.
    """
    household = Household(
        name=name.strip(),
        invite_code=generate_unique_invite_code(db),
        invite_code_expires_at=new_invite_code_expiry(),
    )
    db.add(household)
    db.flush()
    membership = HouseholdMember(household_id=household.id, user_id=user_id, role="admin")
    db.add(membership)
    db.add(Calendar(
        household_id=household.id,
        name=DEFAULT_CALENDAR_NAME,
        color=DEFAULT_CALENDAR_COLOR,
        position=0,
    ))
    db.flush()
    return household, membership


def join_by_invite_code(db: Session, raw_code: str, user_id: uuid.UUID) -> tuple[Household, HouseholdMember]:
    """Tritt per Einladungscode bei (POST /households/join und Registrierung mit Code). Kein Commit.

    Sperrt den Haushalt (CASA-10): Ein paralleler Austritt des letzten Mitglieds
    löscht ihn — danach darf niemand mehr "erfolgreich" beitreten. Unter der Sperre:
    gelöscht, Code inzwischen rotiert oder verwaist (0 Mitglieder) → 404,
    abgelaufen → 410, schon Mitglied → 409 (auch bei parallelem Doppel-Join).
    """
    code = raw_code.strip().upper()
    found = find_household_by_invite_code(db, raw_code)
    household = lock_household(db, found.id)
    if household is None or household.invite_code.upper() != code or member_count(db, household.id) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.INVITE_CODE_NOT_FOUND, "Invite code not found"),
        )
    if is_invite_code_expired(household):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=error_detail(ErrorCode.INVITE_CODE_EXPIRED, "Invite code has expired"),
        )
    if locked_membership(db, household.id, user_id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(ErrorCode.ALREADY_MEMBER, "Already a member of this household"),
        )

    membership = HouseholdMember(household_id=household.id, user_id=user_id, role="member")
    db.add(membership)
    db.flush()
    # Reparatur: Haushalt ohne Admin (Altbestand) bekommt hier wieder einen
    ensure_admin(db, household.id)
    return household, membership


# ---------------------------------------------------------------------------
# Austritt: offene Zuständigkeiten freigeben (PD-H1)
# ---------------------------------------------------------------------------


@dataclass
class ReleaseResult:
    """Was beim Freigeben geändert wurde (für Logs/Tests; Clients laden neu)."""

    todos: list[uuid.UUID] = field(default_factory=list)
    shopping_items: list[uuid.UUID] = field(default_factory=list)
    chore_assignments: list[uuid.UUID] = field(default_factory=list)
    chores: list[uuid.UUID] = field(default_factory=list)
    recurring_bills: list[uuid.UUID] = field(default_factory=list)
    poll_votes: int = 0
    widget_tokens: int = 0

    def areas(self) -> list[str]:
        """Bereiche mit Änderungen — im Socket-Event ``released``, Clients laden diese neu."""
        changed = {
            "todos": self.todos,
            "shopping": self.shopping_items,
            "chores": self.chore_assignments or self.chores,
            "recurring_bills": self.recurring_bills,
            "polls": self.poll_votes,
        }
        return [area for area, value in changed.items() if value]


def _remove_from_rotation(chore: Chore, user_key: str) -> None:
    """Entfernt die Person aus ``rotation_order``; wer als Nächstes dran ist, bleibt gleich.

    Der Scheduler nimmt ``rotation[next_rotation_index % len]`` und überspringt
    Nicht-Mitglieder. Liegt die entfernte Position VOR der nächsten, rutscht die
    nächste Person eine Stelle nach vorn (Index − 1). Ist die entfernte Person selbst
    die nächste, wäre ohnehin die folgende dran — die steht nach dem Entfernen an
    derselben Position (Index bleibt). Liegt sie dahinter, ändert sich nichts.
    Die bereits vollständig durchlaufenen Runden bleiben im Index erhalten, damit
    spätere Korrekturen (``next_rotation_index - gelöschte Termine``) weiter stimmen.
    """
    rotation: list[str] = list(chore.rotation_order or [])
    if user_key not in rotation:
        return
    old_len = len(rotation)
    pos = rotation.index(user_key)
    rounds, current = divmod(max(chore.next_rotation_index, 0), old_len)
    rotation.pop(pos)
    new_len = len(rotation)
    if new_len == 0:
        chore.rotation_order = []
        chore.next_rotation_index = 0
        return
    if pos < current:
        current -= 1
    current %= new_len
    chore.rotation_order = rotation
    chore.next_rotation_index = rounds * new_len + current


def release_departing_member(db: Session, household_id: uuid.UUID, user_id: uuid.UUID) -> ReleaseResult:
    """Gibt die offenen Zuständigkeiten einer austretenden Person frei (gleiche Transaktion).

    - offene Aufgaben und offene Einkaufsartikel: Zuweisung → niemand
    - offene Ämtli-Termine (``completed_at IS NULL``, auch überfällige): → niemand
    - aus ``rotation_order`` aller Ämtli entfernen (nächste Person bleibt gleich)
    - Standard-Zahler wiederkehrender Rechnungen → leer
    - Stimmen in OFFENEN Umfragen löschen (entschiedene bleiben als Geschichte)
    - Widget-Schlüssel der Person für diesen Haushalt löschen

    Erledigtes (Aufgaben, Ämtli, Ausgaben, entschiedene Umfragen) behält die Person.
    ORM-Updates statt Bulk-UPDATE, damit ``version`` (Offline-Sync) hochzählt.
    """
    result = ReleaseResult()
    user_key = str(user_id)

    for todo in db.query(Todo).filter(
        Todo.household_id == household_id,
        Todo.assigned_to_user_id == user_id,
        Todo.is_done == False,  # noqa: E712
    ):
        todo.assigned_to_user_id = None
        result.todos.append(todo.id)

    for item in db.query(ShoppingItem).filter(
        ShoppingItem.household_id == household_id,
        ShoppingItem.assigned_to_user_id == user_id,
        ShoppingItem.is_checked == False,  # noqa: E712
    ):
        item.assigned_to_user_id = None
        result.shopping_items.append(item.id)

    for assignment in db.query(ChoreAssignment).filter(
        ChoreAssignment.household_id == household_id,
        ChoreAssignment.assigned_user_id == user_id,
        ChoreAssignment.completed_at.is_(None),
    ):
        assignment.assigned_user_id = None
        result.chore_assignments.append(assignment.id)

    # rotation_order ist JSON → in Python filtern (wenige Ämtli pro Haushalt)
    for chore in db.query(Chore).filter(Chore.household_id == household_id).with_for_update():
        if user_key in (chore.rotation_order or []):
            _remove_from_rotation(chore, user_key)
            result.chores.append(chore.id)

    for bill in db.query(RecurringBill).filter(
        RecurringBill.household_id == household_id,
        RecurringBill.paid_by_user_id == user_id,
    ):
        bill.paid_by_user_id = None
        result.recurring_bills.append(bill.id)

    open_poll_ids = db.query(EventPoll.id).filter(
        EventPoll.household_id == household_id, EventPoll.status == "offen"
    )
    result.poll_votes = (
        db.query(EventPollVote)
        .filter(
            EventPollVote.household_id == household_id,
            EventPollVote.user_id == user_id,
            EventPollVote.poll_id.in_(open_poll_ids),
        )
        .delete(synchronize_session=False)
    )

    result.widget_tokens = (
        db.query(WidgetToken)
        .filter(WidgetToken.household_id == household_id, WidgetToken.user_id == user_id)
        .delete(synchronize_session=False)
    )

    db.flush()
    return result
