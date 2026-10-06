import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import verify_household_access
from app.database import get_db
from app.models import HouseholdMember, ShoppingItem, ShoppingList
from app.services.client_ids import commit_or_get_existing, get_existing_by_client_id
from app.socket_manager import emit_to_household_sync

# ---------------------------------------------------------------------------
# Store-Normalisierung
# ---------------------------------------------------------------------------
# Stores sind Freitext-Werte auf ShoppingItem (keine eigene Tabelle). Damit
# "Coop", "coop" und "Coop " nicht als drei verschiedene Geschäfte auftauchen:
#   1. Beim Schreiben wird der Wert normalisiert (trim, Mehrfach-Whitespace
#      zusammenfassen, leer → None).
#   2. Existiert im Haushalt bereits ein Store, der sich nur in Gross-/
#      Kleinschreibung unterscheidet, wird dessen Schreibweise übernommen.
#   3. GET /stores und POST /reassign-store arbeiten case-insensitive.
# Der Vergleich läuft bewusst in Python (str.lower) statt per SQL lower():
# SQLite kennt lower() nur für ASCII, PostgreSQL für Unicode — mit Python-
# seitigem Vergleich verhalten sich Tests (SQLite) und Prod (PostgreSQL) gleich.
# Die Menge distinkter Stores pro Haushalt ist klein, der Overhead vernachlässigbar.


def normalize_store(value) -> str | None:
    """Trimmt, fasst Mehrfach-Whitespace zusammen, leerer String → None."""
    if value is None:
        return None
    if not isinstance(value, str):
        return value  # Pydantic meldet den Typfehler
    collapsed = " ".join(value.split())
    return collapsed or None


def store_key(value: str) -> str:
    """Case-insensitiver Gruppierungs-Schlüssel eines (normalisierten) Store-Werts."""
    return value.lower()


def canonical_stores(
    db: Session,
    household_id: uuid.UUID,
    exclude_item_id: uuid.UUID | None = None,
) -> dict[str, str]:
    """
    Liefert pro case-insensitiver Store-Gruppe die kanonische Schreibweise
    des Haushalts: {store_key: kanonischer Wert}.

    Kanonisch = die im Haushalt am häufigsten genutzte Schreibweise;
    bei Gleichstand die alphabetisch kleinste (deterministisch).
    """
    query = (
        db.query(ShoppingItem.store, func.count(ShoppingItem.id))
        .filter(
            ShoppingItem.household_id == household_id,
            ShoppingItem.store.isnot(None),
            ShoppingItem.store != "",
        )
    )
    if exclude_item_id is not None:
        query = query.filter(ShoppingItem.id != exclude_item_id)
    rows = query.group_by(ShoppingItem.store).all()

    groups: dict[str, dict[str, int]] = {}
    for raw_store, count in rows:
        normalized = normalize_store(raw_store)
        if normalized is None:
            continue
        spellings = groups.setdefault(store_key(normalized), {})
        spellings[normalized] = spellings.get(normalized, 0) + count

    return {
        key: sorted(spellings.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        for key, spellings in groups.items()
    }


def resolve_store(
    db: Session,
    household_id: uuid.UUID,
    value: str | None,
    exclude_item_id: uuid.UUID | None = None,
) -> str | None:
    """
    Normalisiert den Store-Wert und übernimmt die bereits im Haushalt genutzte
    Schreibweise, falls ein case-insensitiv gleicher Store existiert.
    """
    normalized = normalize_store(value)
    if normalized is None:
        return None
    canonical = canonical_stores(db, household_id, exclude_item_id=exclude_item_id)
    return canonical.get(store_key(normalized), normalized)


# ---------------------------------------------------------------------------
# Pydantic Schemas — Shopping Lists
# ---------------------------------------------------------------------------


class ShoppingListCreate(BaseModel):
    # Optional client-generierte ID → idempotenter Create (Offline-Sync)
    id: uuid.UUID | None = None
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
    updated_at: datetime
    version: int
    open_count: int = 0  # computed field

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Pydantic Schemas — Shopping Items
# ---------------------------------------------------------------------------


class ShoppingItemCreate(BaseModel):
    # Optional client-generierte ID → idempotenter Create (Offline-Sync)
    id: uuid.UUID | None = None
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

    @field_validator("quantity", "category", mode="before")
    @classmethod
    def empty_string_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("store", mode="before")
    @classmethod
    def normalize_store_value(cls, v):
        return normalize_store(v)


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

    @field_validator("quantity", "category", mode="before")
    @classmethod
    def empty_string_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("store", mode="before")
    @classmethod
    def normalize_store_value(cls, v):
        return normalize_store(v)


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
    updated_at: datetime
    version: int

    model_config = ConfigDict(from_attributes=True)


class ReassignStoreRequest(BaseModel):
    from_store: str = Field(..., min_length=1, max_length=100)
    to_store: str | None = Field(None, max_length=100)

    @field_validator("to_store", mode="before")
    @classmethod
    def normalize_to_store(cls, v):
        return normalize_store(v)

    @field_validator("from_store")
    @classmethod
    def normalize_from_store(cls, v: str) -> str:
        normalized = normalize_store(v)
        if normalized is None:
            raise ValueError("from_store must not be blank")
        return normalized


class ReassignStoreResponse(BaseModel):
    updated: int
    # Tatsächlich geschriebener Ziel-Store: Weicht von `to_store` der Anfrage ab,
    # wenn im Haushalt bereits ein Store existiert, der sich nur in
    # Gross-/Kleinschreibung unterscheidet (Merge in bestehende Schreibweise).
    to_store: str | None = None


# ---------------------------------------------------------------------------
# Router — Shopping Lists
# ---------------------------------------------------------------------------

def _with_open_count(db: Session, lst: ShoppingList) -> ShoppingList:
    """Setzt das berechnete Feld open_count (Anzahl unchecked Items)."""
    lst.open_count = (
        db.query(func.count(ShoppingItem.id))
        .filter(
            ShoppingItem.list_id == lst.id,
            ShoppingItem.is_checked == False,  # noqa: E712
        )
        .scalar()
    )
    return lst


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
    response: Response,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    # Wiederholter Create mit gleicher Client-ID → bestehende Liste, kein neues Event
    existing = get_existing_by_client_id(db, ShoppingList, body.id, household_id)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return _with_open_count(db, existing)

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
    if body.id is not None:
        lst.id = body.id
    db.add(lst)
    existing = commit_or_get_existing(db, ShoppingList, body.id, household_id)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return _with_open_count(db, existing)
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
    _with_open_count(db, lst)

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
# GET  /stores  — Distinct Store-Werte des Haushalts (case-insensitive,
#                 alphabetisch, ohne null). Pro Gruppe die kanonische Schreibweise.
# ---------------------------------------------------------------------------
@router.get("/stores", response_model=list[str])
def list_stores(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    canonical = canonical_stores(db, household_id)
    return [canonical[key] for key in sorted(canonical)]


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
    from_key = store_key(body.from_store)

    # Ziel-Store auflösen: Existiert bereits ein case-insensitiv gleicher Store
    # (ausserhalb der Quell-Gruppe), wird in dessen Schreibweise gemergt.
    # Unterscheidet sich das Ziel nur in Gross-/Kleinschreibung von der Quelle,
    # ist das eine reine Umschreibung → neue Schreibweise des Nutzers gewinnt.
    target_store = body.to_store
    if target_store is not None and store_key(target_store) != from_key:
        canonical = canonical_stores(db, household_id)
        target_store = canonical.get(store_key(target_store), target_store)

    # Quell-Store case-insensitive matchen (inkl. Altdaten mit abweichendem Whitespace)
    affected_items = [
        item
        for item in (
            db.query(ShoppingItem)
            .filter(
                ShoppingItem.household_id == household_id,
                ShoppingItem.store.isnot(None),
                ShoppingItem.store != "",
            )
            .all()
        )
        if (normalized := normalize_store(item.store)) is not None
        and store_key(normalized) == from_key
        and item.store != target_store
    ]

    for item in affected_items:
        item.store = target_store

    db.commit()

    if affected_items:
        emit_to_household_sync(
            household_id,
            "shopping_items_bulk_updated",
            {
                "item_ids": [str(item.id) for item in affected_items],
                "changes": {"store": target_store},
            },
        )

    return ReassignStoreResponse(updated=len(affected_items), to_store=target_store)


# ---------------------------------------------------------------------------
# POST /  — Neues Item erstellen
# ---------------------------------------------------------------------------
@router.post("/", response_model=ShoppingItemResponse, status_code=status.HTTP_201_CREATED)
def create_shopping_item(
    household_id: uuid.UUID,
    body: ShoppingItemCreate,
    response: Response,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    # Wiederholter Create mit gleicher Client-ID → bestehendes Item, kein neues Event
    existing = get_existing_by_client_id(db, ShoppingItem, body.id, household_id)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return existing

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
        store=resolve_store(db, household_id, body.store),
        assigned_to_user_id=body.assigned_to_user_id,
        added_by_user_id=membership.user_id,
    )
    if body.id is not None:
        item.id = body.id
    db.add(item)
    existing = commit_or_get_existing(db, ShoppingItem, body.id, household_id)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return existing
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

    # Store case-insensitive an bestehende Schreibweise im Haushalt angleichen.
    # Das Item selbst wird dabei ausgenommen, damit das einzige Item eines Stores
    # per Edit umgeschrieben werden kann ("coop" → "Coop").
    if "store" in update_data:
        update_data["store"] = resolve_store(
            db, household_id, update_data["store"], exclude_item_id=item.id
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
