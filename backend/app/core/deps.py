import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt import PyJWTError as JWTError
from sqlalchemy.orm import Session

from app.core.error_codes import ErrorCode, error_detail
from app.core.security import decode_access_token
from app.database import get_db
from app.models import User, HouseholdMember

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=error_detail(ErrorCode.INVALID_CREDENTIALS, "Could not validate credentials"),
    )
    try:
        user_id = decode_access_token(token)
        user = db.get(User, uuid.UUID(user_id))
    except (JWTError, KeyError, ValueError):
        raise credentials_exception

    if user is None:
        raise credentials_exception
    return user


def verify_household_access(household_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> HouseholdMember:
    """
    Zentrale Sicherheits-Prüfung: Ist der eingeloggte User Mitglied dieses Haushalts?
    Diese Dependency wird in JEDEM Endpoint verwendet, der auf Household-Daten zugreift.
    """
    membership = db.query(HouseholdMember).filter_by(
        household_id=household_id, user_id=current_user.id
    ).first()

    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail(ErrorCode.NOT_HOUSEHOLD_MEMBER, "Not a member of this household"),
        )
    return membership
