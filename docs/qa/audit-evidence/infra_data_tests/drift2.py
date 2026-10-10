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
    return (insp_def is None) != (rendered_meta_def is None)
def fmt(d):
    if isinstance(d, list): return " | ".join(fmt(x) for x in d)
    op = d[0]
    if op in ("add_fk","remove_fk"):
        fk = d[1]; return f"{op} {fk.parent.name}({','.join(c.name for c in fk.columns)})->{fk.referred_table.name} ondelete={fk.ondelete} name={fk.name}"
    if op in ("add_index","remove_index"):
        ix=d[1]; return f"{op} {ix.table.name}.{ix.name} cols={[c.name for c in ix.columns]} unique={ix.unique}"
    if op in ("add_constraint","remove_constraint"):
        c=d[1]; return f"{op} {c.table.name}.{c.name} {type(c).__name__} cols={[x.name for x in getattr(c,'columns',[])]}"
    if op in ("add_table","remove_table"): return f"{op} {d[1].name}"
    if op in ("add_column","remove_column"): return f"{op} {d[2]}.{d[3].name}"
    if op=="modify_default":
        def r(x): 
            if x is None: return None
            a=getattr(x,'arg',x); return getattr(a,'text',str(a))
        return f"modify_default {d[2]}.{d[3]} db={r(d[5])} model={r(d[6])}"
    if op=="modify_nullable": return f"modify_nullable {d[2]}.{d[3]} db_nullable={d[5]} model_nullable={d[6]}"
    if op=="modify_type": return f"modify_type {d[2]}.{d[3]} db={d[5]} model={d[6]}"
    return str(d)
with eng.connect() as c:
    mc = MigrationContext.configure(c, opts={"compare_type": True, "compare_server_default": csd})
    diff = compare_metadata(mc, Base.metadata)
print("N diffs:", len(diff))
for d in diff: print(fmt(d))
