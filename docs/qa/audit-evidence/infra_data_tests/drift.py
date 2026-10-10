import sys; sys.path.insert(0, sys.argv[1]+"/pg")
import pgharness as H
url = H.fresh_db("infra_drift")
from sqlalchemy import create_engine
from alembic.migration import MigrationContext
from alembic.autogenerate import compare_metadata
import app.models
from app.database import Base
eng = create_engine(url)
def csd(context, insp_col, meta_col, insp_def, meta_def, rendered_meta_def):
    a = (insp_def or "").split("::")[0].strip("'") if insp_def else None
    b = rendered_meta_def.strip("'") if rendered_meta_def else None
    if a is None and b is None: return False
    if (a is None) != (b is None): return True
    return a.lower() != b.lower().strip("'")
with eng.connect() as c:
    mc = MigrationContext.configure(c, opts={"compare_type": True, "compare_server_default": csd})
    diff = compare_metadata(mc, Base.metadata)
import pprint
print("N diffs:", len(diff))
for d in diff: pprint.pprint(d, width=220)
