"""Tests für verify_household_admin Dependency."""
import uuid
import pytest
from app.core.deps import verify_household_admin
from app.core.error_codes import ErrorCode
from app.models import HouseholdMember
from fastapi import HTTPException


def test_admin_passes(db, household_a, user_a):
    """Admin-Mitglied passiert den Guard."""
    membership = db.query(HouseholdMember).filter_by(
        household_id=household_a.id, user_id=user_a.id
    ).first()
    assert membership.role == "admin"
    result = verify_household_admin(membership=membership)
    assert result == membership


def test_non_admin_rejected(db, household_a, user_a):
    """Member-Rolle wird abgelehnt mit 403 ADMIN_REQUIRED."""
    membership = db.query(HouseholdMember).filter_by(
        household_id=household_a.id, user_id=user_a.id
    ).first()
    # Rolle temporär ändern
    membership.role = "member"
    db.flush()

    with pytest.raises(HTTPException) as exc_info:
        verify_household_admin(membership=membership)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == ErrorCode.ADMIN_REQUIRED
