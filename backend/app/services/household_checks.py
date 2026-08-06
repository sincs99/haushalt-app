import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.error_codes import ErrorCode, error_detail
from app.models import HouseholdMember


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
