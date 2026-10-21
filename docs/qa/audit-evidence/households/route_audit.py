"""Static route audit: which routes depend on verify_household_access / admin / get_current_user."""
import sys, os, collections
os.environ.setdefault("DATABASE_URL", "postgresql://audit:audit@localhost:5432/postgres")
os.environ.setdefault("JWT_SECRET_KEY", "audit-secret-key-only-for-tests-min32-xyz")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
sys.path.insert(0, "/home/user/haushalt-app/backend")
from app.main import app
from app.core.deps import verify_household_access, verify_household_admin, get_current_user
def deps(d, acc):
    for sub in d.dependencies:
        acc.add(sub.call); deps(sub, acc)
    return acc
admin, member, user_only, none = [], [], [], []
def walk(routes):
    for r in routes:
        o = getattr(r, "original_router", None)
        if o is not None: yield from walk(o.routes)
        else: yield r
for r in walk(app.routes):
    if not hasattr(r, "dependant"): continue
    s = deps(r.dependant, set())
    m = ",".join(sorted(r.methods - {"HEAD"})) if hasattr(r, "methods") else ""
    row = f"{m:6} {r.path}"
    if verify_household_admin in s: admin.append(row)
    elif verify_household_access in s: member.append(row)
    elif get_current_user in s: user_only.append(row)
    else: none.append(row)
print("ADMIN:", *admin, sep="\n  ")
print(f"\nMEMBER: {len(member)} routes")
print("\nUSER-ONLY (no household dep):", *user_only, sep="\n  ")
print("\nNO AUTH DEP:", *none, sep="\n  ")
print("\nhousehold_id routes lacking membership dep:", [x for x in user_only + none if "{household_id}" in x])
