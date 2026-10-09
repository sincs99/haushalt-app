"""Plattform-Admin vergeben oder entziehen.

    python -m scripts.make_platform_admin --email admin@example.com
    python -m scripts.make_platform_admin --email admin@example.com --revoke

Im Docker-Setup: docker compose exec backend python -m scripts.make_platform_admin --email …
"""

import argparse
import sys

from app.database import SessionLocal
from app.models import User


def main() -> int:
    parser = argparse.ArgumentParser(description="Plattform-Admin vergeben/entziehen")
    parser.add_argument("--email", required=True)
    parser.add_argument("--revoke", action="store_true", help="Admin-Recht entziehen")
    args = parser.parse_args()

    with SessionLocal() as db:
        user = db.query(User).filter_by(email=args.email.strip()).first()
        if user is None or user.deleted_at is not None:
            print(f"Kein Konto mit E-Mail {args.email!r}", file=sys.stderr)
            return 1
        user.is_platform_admin = not args.revoke
        db.commit()
        state = "entzogen" if args.revoke else "vergeben"
        print(f"Plattform-Admin für {user.email} {state}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
