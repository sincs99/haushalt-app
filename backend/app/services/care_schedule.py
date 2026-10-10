"""Fälligkeiten wiederkehrender Pflegeaufgaben (Tiere und Pflanzen).

E-1 (PD-P4): nächste Fälligkeit = Erledigungstag + Intervall.
E-2 (PD-P4): Ändert sich das Intervall, wird die Fälligkeit neu berechnet —
``(last_done_at or heute) + neues Intervall`` — und die Erinnerung zurückgesetzt.
Sonst bliebe nach einer Intervall-Änderung (auch durch einen übernommenen
KI-Vorschlag) der alte Termin stehen und die Änderung wirkte erst einen Zyklus später.
"""

from datetime import date, timedelta
from typing import Any


def apply_care_task_update(task: Any, update_data: dict[str, Any], today: date) -> None:
    """Wendet ein PATCH auf eine Pflegeaufgabe (PetCareTask/PlantCareTask) an.

    Eine explizit mitgeschickte ``next_due_at`` hat Vorrang vor der Neuberechnung.
    """
    old_interval = task.interval_days
    for key, value in update_data.items():
        setattr(task, key, value)

    if "next_due_at" in update_data:
        # Neue Fälligkeit → zur neuen Fälligkeit wieder erinnern
        task.notified_at = None
    elif task.interval_days != old_interval:
        task.next_due_at = (task.last_done_at or today) + timedelta(days=task.interval_days)
        task.notified_at = None
