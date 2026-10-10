"""Basis für PATCH-Bodies: explizites ``null`` auf NOT-NULL-Feldern → 422 (F0-3, CASA-04/37).

In Teil-Updates bedeutet ein weggelassenes Feld "nicht ändern"; ``null`` heisst
"leeren". Für Spalten, die in der DB NOT NULL sind, ist "leeren" unmöglich — ohne
Prüfung landete ``None`` per ``setattr`` im Modell: JSON-Spalten speicherten das
JSON-Literal ``null`` (Modul danach für den ganzen Haushalt kaputt, CASA-04), alle
anderen liefen erst beim Commit in den Constraint (500, CASA-37).

Verwendung::

    class EventUpdate(PatchModel):
        __orm_model__ = Event
        title: str | None = None
        ...

Welche Felder kein ``null`` dürfen, wird aus der Nullability der gleichnamigen
Modellspalten abgeleitet — neue NOT-NULL-Spalten sind damit automatisch geschützt.
Felder ohne gleichnamige Spalte (z. B. ``shares``) bleiben unberührt; zusätzliche
Felder lassen sich über ``__extra_non_nullable__`` sperren. Validatoren, die ``None``
bewusst umdeuten (z. B. ``steps: null → []``), laufen vorher und bleiben gültig.
"""

from typing import Any, ClassVar

from pydantic import BaseModel, model_validator
from pydantic_core import PydanticCustomError


class PatchModel(BaseModel):
    __orm_model__: ClassVar[Any] = None
    __extra_non_nullable__: ClassVar[tuple[str, ...]] = ()
    __non_nullable_fields__: ClassVar[frozenset[str]] = frozenset()

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        names = set(cls.__extra_non_nullable__)
        unknown = names - set(cls.model_fields)
        if unknown:
            raise TypeError(f"{cls.__name__}.__extra_non_nullable__: unknown fields {sorted(unknown)}")
        if cls.__orm_model__ is not None:
            columns = cls.__orm_model__.__table__.columns
            names |= {
                name
                for name in cls.model_fields
                if name in columns and not columns[name].nullable
            }
        cls.__non_nullable_fields__ = frozenset(names)

    @model_validator(mode="after")
    def _reject_explicit_null(self):
        for name in sorted(self.__non_nullable_fields__):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise PydanticCustomError(
                    "null_not_allowed",
                    "{field} must not be null",
                    {"field": name},
                )
        return self
