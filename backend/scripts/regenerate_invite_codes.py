"""
Regeneriert Invite-Codes für Households, die nicht dem aktuellen Format entsprechen.

Nutzung:
    cd backend
    python -m scripts.regenerate_invite_codes          # Dry-Run (Default)
    python -m scripts.regenerate_invite_codes --apply   # Tatsächlich ändern
"""
import argparse
import re
import sys

from app.database import SessionLocal
from app.models import Household
from app.core.security import generate_invite_code

VALID_PATTERN = re.compile(r"^[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{8}$")


def main():
    parser = argparse.ArgumentParser(
        description="Regenerate non-conforming invite codes",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually apply changes (default: dry-run)",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        households = db.query(Household).all()
        existing_codes = {h.invite_code for h in households}

        to_update = [h for h in households if not VALID_PATTERN.match(h.invite_code)]

        if not to_update:
            print("✅ Alle Households haben bereits konforme Invite-Codes.")
            return

        print(
            f"🔍 {len(to_update)} Household(s) mit nicht-konformem Invite-Code gefunden:\n"
        )

        for h in to_update:
            # Neuen Code generieren, der nicht kollidiert
            for _ in range(100):
                new_code = generate_invite_code()
                if new_code not in existing_codes:
                    break
            else:
                print(
                    f"  ❌ {h.name} ({h.invite_code}): "
                    "Konnte keinen eindeutigen Code generieren!"
                )
                continue

            action = "🔄" if args.apply else "👁️"
            print(f"  {action} {h.name}: {h.invite_code} → {new_code}")

            if args.apply:
                existing_codes.discard(h.invite_code)
                h.invite_code = new_code
                existing_codes.add(new_code)

        if args.apply:
            db.commit()
            print(f"\n✅ {len(to_update)} Invite-Code(s) aktualisiert.")
        else:
            print(
                "\n📋 Dry-Run: Keine Änderungen vorgenommen. Mit --apply ausführen."
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
