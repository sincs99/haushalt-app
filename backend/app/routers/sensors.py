"""Raumklima: Sensoren (Temperatur, Luftfeuchtigkeit, Batterie) eines Haushalts.

Zwei Router:

- ``manage_router`` (normaler Login): Sensoren auflisten, umbenennen, löschen,
  Verlauf lesen; Admins verwalten den Schreib-Schlüssel des Haushalts.
- ``router``: ``POST /api/sensors/ingest`` mit ``Authorization: Bearer hs_…``.
  Der Schlüssel erlaubt nur diesen einen Endpoint, läuft nicht ab und gehört
  dem Haushalt. Damit liefert eine Brücke (z. B. Zigbee2MQTT, Home Assistant)
  Messwerte, ohne ein Benutzerkonto zu brauchen.

Die Quelle ist dem Backend egal: Ein Gerät wird über ``device_id`` der Quelle
erkannt und beim ersten Messwert angelegt. Der letzte Stand steht am Gerät;
der Verlauf wird ausgedünnt gespeichert (höchstens ein Eintrag pro Gerät in
``HISTORY_INTERVAL``) und nach ``HISTORY_RETENTION`` gelöscht.

Gespeichert wird nur der SHA-256-Hash des Schlüssels. Doku: docs/sensors.md
"""

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.core.deps import verify_household_access, verify_household_admin
from app.core.error_codes import ErrorCode, error_detail
from app.core.patch_schema import PatchModel
from app.core.rate_limit import limiter
from app.core.security import hash_refresh_token
from app.database import get_db
from app.models import HouseholdMember, SensorDevice, SensorIngestToken, SensorReading
from app.services.locking import lock_household
from app.socket_manager import emit_to_household_sync

TOKEN_PREFIX = "hs_"
MAX_DEVICES_PER_HOUSEHOLD = 50
MAX_READINGS_PER_REQUEST = 50
HISTORY_INTERVAL = timedelta(minutes=5)
HISTORY_RETENTION = timedelta(days=30)
# Ab dieser Spanne liefert der Verlauf Stundenmittel statt Einzelwerten
HOURLY_BUCKETS_FROM_HOURS = 48


def _hash(token: str) -> str:
    return hash_refresh_token(token)  # SHA-256, wie Refresh-Tokens


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite (Tests) liefert naive Datetimes; gespeichert ist immer UTC."""
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SensorDeviceResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    external_id: str
    name: str
    room: str | None
    temperature: float | None
    humidity: float | None
    battery: float | None
    last_seen_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("last_seen_at", "created_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return _aware(v)


class SensorDeviceUpdate(PatchModel):
    # null auf NOT-NULL-Spalten von SensorDevice → 422 (app/core/patch_schema.py)
    __orm_model__ = SensorDevice

    name: str | None = Field(None, min_length=1, max_length=80)
    room: str | None = Field(None, max_length=60)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Name must not be blank")
        return v.strip() if v is not None else v

    @field_validator("room", mode="before")
    @classmethod
    def normalize_empty_room(cls, v):
        if isinstance(v, str):
            return v.strip() or None
        return v


class SensorReadingPoint(BaseModel):
    recorded_at: datetime
    temperature: float | None
    humidity: float | None


class IngestTokenStatus(BaseModel):
    exists: bool
    token_prefix: str | None = None
    created_at: datetime | None = None
    last_used_at: datetime | None = None


class IngestTokenCreated(BaseModel):
    token: str
    token_prefix: str
    created_at: datetime


class IngestReading(BaseModel):
    """Ein Messwert einer Quelle. Fehlende Felder lassen den letzten Stand stehen."""

    device_id: str = Field(..., min_length=1, max_length=100)
    # Nur beim Anlegen verwendet; ein in der App geänderter Name bleibt bestehen
    name: str | None = Field(None, max_length=80)
    temperature: float | None = Field(None, ge=-60, le=100)
    humidity: float | None = Field(None, ge=0, le=100)
    battery: float | None = Field(None, ge=0, le=100)

    @field_validator("device_id")
    @classmethod
    def device_id_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("device_id must not be blank")
        return v.strip()

    @model_validator(mode="after")
    def needs_a_value(self):
        if self.temperature is None and self.humidity is None and self.battery is None:
            raise ValueError("At least one of temperature, humidity, battery is required")
        return self


class IngestRequest(BaseModel):
    readings: list[IngestReading] = Field(..., min_length=1, max_length=MAX_READINGS_PER_REQUEST)


class IngestResponse(BaseModel):
    accepted: int
    # device_id der Messwerte, die wegen der Geräte-Obergrenze verworfen wurden
    rejected: list[str]


# ---------------------------------------------------------------------------
# Sensoren und Schlüssel verwalten (Login nötig)
# ---------------------------------------------------------------------------

manage_router = APIRouter(
    prefix="/api/households/{household_id}/sensors",
    tags=["sensors"],
)


def _household_token(db: Session, household_id: uuid.UUID) -> SensorIngestToken | None:
    return db.query(SensorIngestToken).filter(SensorIngestToken.household_id == household_id).first()


def _device_or_404(db: Session, household_id: uuid.UUID, device_id: uuid.UUID) -> SensorDevice:
    device = db.get(SensorDevice, device_id)
    if device is None or device.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.SENSOR_NOT_FOUND, "Sensor not found in this household"),
        )
    return device


def _device_payload(device: SensorDevice) -> dict:
    return SensorDeviceResponse.model_validate(device).model_dump(mode="json")


# Schlüssel-Routen stehen vor "/{device_id}", damit "ingest-token" nicht als ID gilt


@manage_router.get("/ingest-token", response_model=IngestTokenStatus)
def get_ingest_token(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    token = _household_token(db, household_id)
    if token is None:
        return IngestTokenStatus(exists=False)
    return IngestTokenStatus(
        exists=True,
        token_prefix=token.token_prefix,
        created_at=_aware(token.created_at),
        last_used_at=_aware(token.last_used_at),
    )


@manage_router.post("/ingest-token", response_model=IngestTokenCreated, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def create_ingest_token(
    request: Request,
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_admin),
    db: Session = Depends(get_db),
):
    """Erzeugt einen neuen Schlüssel; ein bestehender wird dabei ungültig.

    Parallele Aufrufe laufen unter der Haushaltssperre nacheinander: Am Ende gilt
    genau ein Schlüssel, der zuletzt ausgegebene.
    """
    if lock_household(db, household_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.HOUSEHOLD_NOT_FOUND, "Household not found"),
        )
    existing = _household_token(db, household_id)
    if existing is not None:
        db.delete(existing)
        db.flush()

    plain = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token = SensorIngestToken(
        household_id=household_id,
        token_hash=_hash(plain),
        token_prefix=plain[:10],
    )
    db.add(token)
    db.flush()
    # Antwort vor dem Commit bauen: Danach kann ein paralleler Aufruf den Schlüssel
    # schon ersetzt haben
    result = IngestTokenCreated(token=plain, token_prefix=token.token_prefix, created_at=_aware(token.created_at))
    db.commit()
    return result


@manage_router.delete("/ingest-token", status_code=status.HTTP_204_NO_CONTENT)
def delete_ingest_token(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_admin),
    db: Session = Depends(get_db),
):
    token = _household_token(db, household_id)
    if token is not None:
        db.delete(token)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@manage_router.get("", response_model=list[SensorDeviceResponse])
def list_sensors(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    return (
        db.query(SensorDevice)
        .filter(SensorDevice.household_id == household_id)
        .order_by(SensorDevice.room.asc(), SensorDevice.name.asc())
        .all()
    )


@manage_router.patch("/{device_id}", response_model=SensorDeviceResponse)
def update_sensor(
    household_id: uuid.UUID,
    device_id: uuid.UUID,
    body: SensorDeviceUpdate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    device = _device_or_404(db, household_id, device_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(device, field, value)
    db.commit()
    db.refresh(device)

    emit_to_household_sync(household_id, "sensor_updated", _device_payload(device))
    return device


@manage_router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sensor(
    household_id: uuid.UUID,
    device_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    """Löscht Sensor und Verlauf. Liefert die Quelle weiter, entsteht er neu."""
    device = _device_or_404(db, household_id, device_id)
    # Ausdrücklich löschen statt auf ON DELETE CASCADE zu bauen (SQLite ohne FK-Pragma)
    db.query(SensorReading).filter(SensorReading.device_id == device.id).delete(synchronize_session=False)
    db.delete(device)
    db.commit()

    emit_to_household_sync(household_id, "sensor_deleted", {"id": str(device_id)})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@manage_router.get("/{device_id}/readings", response_model=list[SensorReadingPoint])
def list_readings(
    household_id: uuid.UUID,
    device_id: uuid.UUID,
    hours: int = Query(24, ge=1, le=24 * 30),
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    """Verlauf der letzten ``hours`` Stunden, älteste zuerst.

    Bis 48 Stunden Einzelwerte, darüber Stundenmittel (hält die Antwort klein).
    """
    device = _device_or_404(db, household_id, device_id)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (
        db.query(SensorReading)
        .filter(SensorReading.device_id == device.id, SensorReading.recorded_at >= since)
        .order_by(SensorReading.recorded_at.asc())
        .all()
    )
    points = [
        SensorReadingPoint(recorded_at=_aware(r.recorded_at), temperature=r.temperature, humidity=r.humidity)
        for r in rows
    ]
    if hours <= HOURLY_BUCKETS_FROM_HOURS:
        return points
    return _hourly_means(points)


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _hourly_means(points: list[SensorReadingPoint]) -> list[SensorReadingPoint]:
    buckets: dict[datetime, list[SensorReadingPoint]] = {}
    for point in points:
        hour = point.recorded_at.replace(minute=0, second=0, microsecond=0)
        buckets.setdefault(hour, []).append(point)
    return [
        SensorReadingPoint(
            # Mitte der Stunde, damit die Linie nicht nach links verschoben wirkt
            recorded_at=hour + timedelta(minutes=30),
            temperature=_mean([p.temperature for p in group if p.temperature is not None]),
            humidity=_mean([p.humidity for p in group if p.humidity is not None]),
        )
        for hour, group in sorted(buckets.items())
    ]


# ---------------------------------------------------------------------------
# Messwerte liefern (nur mit Schreib-Schlüssel)
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/sensors", tags=["sensors"])


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=error_detail(ErrorCode.SENSOR_TOKEN_INVALID, "Invalid or revoked sensor key"),
    )


def _resolve_token(db: Session, authorization: str | None) -> SensorIngestToken:
    if not authorization or not authorization.startswith("Bearer "):
        raise _unauthorized()
    plain = authorization.removeprefix("Bearer ").strip()
    if not plain.startswith(TOKEN_PREFIX):
        raise _unauthorized()
    token = db.query(SensorIngestToken).filter(SensorIngestToken.token_hash == _hash(plain)).first()
    if token is None:
        raise _unauthorized()
    return token


@router.post("/ingest", response_model=IngestResponse)
@limiter.limit("120/minute")
def ingest_readings(
    request: Request,
    body: IngestRequest,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    token = _resolve_token(db, authorization)
    household_id = token.household_id
    # Serialisiert parallele Lieferungen: kein doppeltes Anlegen desselben Geräts,
    # die Geräte-Obergrenze gilt exakt
    if lock_household(db, household_id) is None:
        raise _unauthorized()

    now = datetime.now(timezone.utc)
    devices = {
        d.external_id: d
        for d in db.query(SensorDevice).filter(SensorDevice.household_id == household_id).all()
    }
    touched: dict[str, SensorDevice] = {}
    rejected: list[str] = []
    accepted = 0

    for reading in body.readings:
        device = devices.get(reading.device_id)
        if device is None:
            if len(devices) >= MAX_DEVICES_PER_HOUSEHOLD:
                if reading.device_id not in rejected:
                    rejected.append(reading.device_id)
                continue
            device = SensorDevice(
                household_id=household_id,
                external_id=reading.device_id,
                name=(reading.name or "").strip() or reading.device_id[:80],
            )
            db.add(device)
            devices[reading.device_id] = device

        if reading.temperature is not None:
            device.temperature = reading.temperature
        if reading.humidity is not None:
            device.humidity = reading.humidity
        if reading.battery is not None:
            device.battery = reading.battery
        device.last_seen_at = now
        touched[reading.device_id] = device
        accepted += 1

    db.flush()  # IDs neuer Geräte für die Verlaufseinträge

    for device in touched.values():
        if device.temperature is None and device.humidity is None:
            continue  # nur Batterie bekannt: nichts für den Verlauf
        last_logged = _aware(device.last_logged_at)
        if last_logged is not None and now - last_logged < HISTORY_INTERVAL:
            continue
        db.add(
            SensorReading(
                device_id=device.id,
                recorded_at=now,
                temperature=device.temperature,
                humidity=device.humidity,
            )
        )
        device.last_logged_at = now
        db.query(SensorReading).filter(
            SensorReading.device_id == device.id,
            SensorReading.recorded_at < now - HISTORY_RETENTION,
        ).delete(synchronize_session=False)

    token.last_used_at = now
    db.flush()
    payloads = [_device_payload(device) for device in touched.values()]
    db.commit()

    for payload in payloads:
        emit_to_household_sync(household_id, "sensor_updated", payload)
    return IngestResponse(accepted=accepted, rejected=rejected)
