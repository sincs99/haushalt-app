import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, verify_household_access
from app.database import get_db
from app.models import HouseholdMember, ShoppingItem, ShoppingList, User
from app.socket_manager import emit_to_household_sync

# ---------------------------------------------------------------------------
# Pydantic Schemas — Shopping Lists
# ---------------------------------------------------------------------------


class ShoppingListCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    icon: str | None = Field(None, max_length=50)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name must not be blank")
        return v.strip()


class ShoppingListUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    icon: str | None = Field(None, max_length=50)
    position: int | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Name must not be blank")
        return v.strip() if v is not None else v


class ShoppingListResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    name: str
    icon: str | None
    position: int
    created_at: datetime
    open_count: int = 0  # computed field

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Pydantic Schemas — Shopping Items
# ---------------------------------------------------------------------------


class ShoppingItemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    list_id: uuid.UUID
    quantity: str | None = Field(None, max_length=50)
    category: str | None = Field(None, max_length=50)
    store: str | None = Field(None, max_length=100)
    assigned_to_user_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name must not be blank")
        return v.strip()

    @field_validator("quantity", "category", "store", mode="before")
    @classmethod
    def empty_string_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v


class ShoppingItemUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    quantity: str | None = Field(None, max_length=50)
    category: str | None = Field(None, max_length=50)
    is_checked: bool | None = None
    store: str | None = Field(None, max_length=100)
    assigned_to_user_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Name must not be blank")
        return v.strip() if v is not None else v

    @field_validator("quantity", "category", "store", mode="before")
    @classmethod
    def empty_string_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v


class ShoppingItemResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    list_id: uuid.UUID
    name: str
    quantity: str | None
    category: str | None
    is_checked: bool
    added_by_user_id: uuid.UUID | None
    created_at: datetime
    checked_at: datetime | None
    store: str | None
    assigned_to_user_id: uuid.UUID | None

    model_config = ConfigDict(from_attributes=True)


class ReassignStoreRequest(BaseModel):
    from_store: str = Field(..., min_length=1, max_length=100)
    to_store: str | None = Field(None, max_length=100)

    @field_validator("to_store", mode="before")
    @classmethod
    def empty_string_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v.strip() if isinstance(v, str) else v

    @field_validator("from_store")
    @classmethod
    def strip_from_store(cls, v: str) -> str:
        return v.strip()


class ReassignStoreResponse(BaseModel):
    updated: int


# ---------------------------------------------------------------------------
# Router — Shopping Lists
# ---------------------------------------------------------------------------

list_router = APIRouter(
    prefix="/api/households/{household_id}/shopping-lists",
    tags=["shopping"],
)


# ---------------------------------------------------------------------------
# GET  /  — Alle Listen eines Haushalts (sortiert nach position)
# ---------------------------------------------------------------------------
@list_router.get("/", response_model=list[ShoppingListResponse])
def list_shopping_lists(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    lists = (
        db.query(ShoppingList)
        .filter(ShoppingList.household_id == household_id)
        .order_by(ShoppingList.position)
        .all()
    )

    # open_count berechnen (Anzahl unchecked Items pro Liste)
    for lst in lists:
        lst.open_count = (
            db.query(func.count(ShoppingItem.id))
            .filter(
                ShoppingItem.list_id == lst.id,
                ShoppingItem.is_checked == False,  # noqa: E712
            )
            .scalar()
        )

    return lists


# ---------------------------------------------------------------------------
# POST /  — Neue Liste erstellen
# ---------------------------------------------------------------------------
@list_router.post("/", response_model=ShoppingListResponse, status_code=status.HTTP_201_CREATED)
def create_shopping_list(
    household_id: uuid.UUID,
    body: ShoppingListCreate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    # Position = max(position) + 1 unter existierenden Listen des Haushalts
    max_pos = (
        db.query(func.max(ShoppingList.position))
        .filter(ShoppingList.household_id == household_id)
        .scalar()
    )
    next_position = (max_pos or 0) + 1

    lst = ShoppingList(
        household_id=household_id,
        name=body.name,
        icon=body.icon,
        position=next_position,
    )
    db.add(lst)
    db.commit()
    db.refresh(lst)

    lst.open_count = 0  # neue Liste hat keine Items

    response_data = ShoppingListResponse.model_validate(lst).model_dump(mode="json")
    emit_to_household_sync(household_id, "shopping_list_created", response_data)
    return lst


# ---------------------------------------------------------------------------
# PATCH /{list_id}  — Liste umbenennen / icon / position
# ---------------------------------------------------------------------------
@list_router.patch("/{list_id}", response_model=ShoppingListResponse)
def update_shopping_list(
    household_id: uuid.UUID,
    list_id: uuid.UUID,
    body: ShoppingListUpdate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    lst = db.get(ShoppingList, list_id)
    if lst is None or lst.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shopping list not found",
        )

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(lst, field, value)

    db.commit()
    db.refresh(lst)

    # open_count berechnen
    lst.open_count = (
        db.query(func.count(ShoppingItem.id))
        .filter(
            ShoppingItem.list_id == lst.id,
            ShoppingItem.is_checked == False,  # noqa: E712
        )
        .scalar()
    )

    response_data = ShoppingListResponse.model_validate(lst).model_dump(mode="json")
    emit_to_household_sync(household_id, "shopping_list_updated", response_data)
    return lst


# ---------------------------------------------------------------------------
# DELETE /{list_id}  — Liste löschen (nur wenn leer ODER force=true)
# ---------------------------------------------------------------------------
# Design Decision: Alle Mitglieder (nicht nur Admins) dürfen mit ?force=true löschen.
# Konsistent mit dem Rest der App, wo alle Mitglieder CRUD-Rechte haben.
# Bei Bedarf auf verify_household_admin wechseln.
@list_router.delete("/{list_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shopping_list(
    household_id: uuid.UUID,
    list_id: uuid.UUID,
    force: bool = False,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    lst = db.get(ShoppingList, list_id)
    if lst is None or lst.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shopping list not found",
        )

    item_count = (
        db.query(func.count(ShoppingItem.id))
        .filter(ShoppingItem.list_id == list_id)
        .scalar()
    )
    if item_count > 0 and not force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"List contains {item_count} items. Use ?force=true to delete.",
        )

    db.delete(lst)  # CASCADE löscht Items
    db.commit()

    emit_to_household_sync(household_id, "shopping_list_deleted", {"id": str(list_id)})


# ---------------------------------------------------------------------------
# Router — Shopping Items
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/households/{household_id}/shopping-items",
    tags=["shopping"],
)


# ---------------------------------------------------------------------------
# GET  /  — Liste aller Shopping-Items (mit optionalem list_id-Filter)
# ---------------------------------------------------------------------------
@router.get("/", response_model=list[ShoppingItemResponse])
def list_shopping_items(
    household_id: uuid.UUID,
    list_id: uuid.UUID | None = None,
    include_checked: bool = False,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    query = db.query(ShoppingItem).filter(
        ShoppingItem.household_id == household_id
    )
    if list_id is not None:
        query = query.filter(ShoppingItem.list_id == list_id)
    if not include_checked:
        query = query.filter(ShoppingItem.is_checked == False)  # noqa: E712

    return query.order_by(ShoppingItem.created_at).all()


# ---------------------------------------------------------------------------
# GET  /stores  — Distinct Store-Werte des Haushalts (alphabetisch, ohne null)
# ---------------------------------------------------------------------------
@router.get("/stores", response_model=list[str])
def list_stores(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(ShoppingItem.store)
        .filter(
            ShoppingItem.household_id == household_id,
            ShoppingItem.store.isnot(None),
            ShoppingItem.store != "",
        )
        .distinct()
        .order_by(ShoppingItem.store)
        .all()
    )
    return [row[0] for row in rows]


# ---------------------------------------------------------------------------
# POST /reassign-store  — Store-Wert für alle Items umbenennen / auflösen
# ---------------------------------------------------------------------------
@router.post("/reassign-store", response_model=ReassignStoreResponse)
def reassign_store(
    household_id: uuid.UUID,
    body: ReassignStoreRequest,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    affected_items = (
        db.query(ShoppingItem)
        .filter(
            ShoppingItem.household_id == household_id,
            ShoppingItem.store == body.from_store,
        )
        .all()
    )

    for item in affected_items:
        item.store = body.to_store

    db.commit()

    if affected_items:
        emit_to_household_sync(
            household_id,
            "shopping_items_bulk_updated",
            {
                "item_ids": [str(item.id) for item in affected_items],
                "changes": {"store": body.to_store},
            },
        )

    return ReassignStoreResponse(updated=len(affected_items))


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
    # Konsistenz-Check: list_id muss zu einer Liste des gleichen Haushalts gehören
    shopping_list = db.get(ShoppingList, body.list_id)
    if shopping_list is None or shopping_list.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="list_id does not belong to this household",
        )

    # assigned_to_user_id validieren (muss Haushaltsmitglied sein)
    if body.assigned_to_user_id is not None:
        is_member = (
            db.query(HouseholdMember)
            .filter_by(
                household_id=household_id,
                user_id=body.assigned_to_user_id,
            )
            .first()
        )
        if not is_member:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="assigned_to_user_id is not a member of this household",
            )

    item = ShoppingItem(
        household_id=household_id,
        list_id=body.list_id,
        name=body.name,
        quantity=body.quantity,
        category=body.category,
        store=body.store,
        assigned_to_user_id=body.assigned_to_user_id,
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

    # assigned_to_user_id validieren (muss Haushaltsmitglied sein)
    if "assigned_to_user_id" in update_data and update_data["assigned_to_user_id"] is not None:
        is_member = (
            db.query(HouseholdMember)
            .filter_by(
                household_id=household_id,
                user_id=update_data["assigned_to_user_id"],
            )
            .first()
        )
        if not is_member:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="assigned_to_user_id is not a member of this household",
            )

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
