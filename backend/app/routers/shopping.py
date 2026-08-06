import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, verify_household_access
from app.database import get_db
from app.models import HouseholdMember, ShoppingItem, User
from app.socket_manager import emit_to_household_sync

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class ShoppingItemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    quantity: str | None = Field(None, max_length=50)
    category: str | None = Field(None, max_length=50)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name must not be blank")
        return v.strip()

    @field_validator("quantity", "category", mode="before")
    @classmethod
    def empty_string_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v


class ShoppingItemUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    quantity: str | None = None
    category: str | None = None
    is_checked: bool | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Name must not be blank")
        return v.strip() if v is not None else v

    @field_validator("quantity", "category", mode="before")
    @classmethod
    def empty_string_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v


class ShoppingItemResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    name: str
    quantity: str | None
    category: str | None
    is_checked: bool
    added_by_user_id: uuid.UUID | None
    created_at: datetime
    checked_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/households/{household_id}/shopping-items",
    tags=["shopping"],
)


# ---------------------------------------------------------------------------
# GET  /  — Liste aller Shopping-Items
# ---------------------------------------------------------------------------
@router.get("/", response_model=list[ShoppingItemResponse])
def list_shopping_items(
    household_id: uuid.UUID,
    include_checked: bool = False,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    query = db.query(ShoppingItem).filter(
        ShoppingItem.household_id == household_id
    )
    if not include_checked:
        query = query.filter(ShoppingItem.is_checked == False)  # noqa: E712

    return query.order_by(ShoppingItem.created_at).all()


# ---------------------------------------------------------------------------
# POST /  — Neues Item erstellen
# ---------------------------------------------------------------------------
@router.post("/", response_model=ShoppingItemResponse, status_code=status.HTTP_201_CREATED)
def create_shopping_item(
    household_id: uuid.UUID,
    body: ShoppingItemCreate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    item = ShoppingItem(
        household_id=household_id,
        name=body.name,
        quantity=body.quantity,
        category=body.category,
        added_by_user_id=membership.user_id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    emit_to_household_sync(
        household_id,
        "shopping_item_created",
        ShoppingItemResponse.model_validate(item).model_dump(mode="json"),
    )
    return item


# ---------------------------------------------------------------------------
# PATCH /{item_id}  — Item aktualisieren (partial update)
# ---------------------------------------------------------------------------
@router.patch("/{item_id}", response_model=ShoppingItemResponse)
def update_shopping_item(
    household_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ShoppingItemUpdate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    item = db.get(ShoppingItem, item_id)
    if item is None or item.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shopping item not found in this household",
        )

    update_data = body.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(item, field, value)

    # checked_at Logik
    if "is_checked" in update_data:
        if update_data["is_checked"] is True:
            item.checked_at = datetime.now(timezone.utc)
        else:
            item.checked_at = None

    db.commit()
    db.refresh(item)

    emit_to_household_sync(
        household_id,
        "shopping_item_updated",
        ShoppingItemResponse.model_validate(item).model_dump(mode="json"),
    )
    return item


# ---------------------------------------------------------------------------
# DELETE /{item_id}  — Item löschen
# ---------------------------------------------------------------------------
@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shopping_item(
    household_id: uuid.UUID,
    item_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    item = db.get(ShoppingItem, item_id)
    if item is None or item.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shopping item not found in this household",
        )

    db.delete(item)
    db.commit()

    emit_to_household_sync(
        household_id,
        "shopping_item_deleted",
        {"id": str(item_id)},
    )
