"""Push scheduler: multi-worker dedupe for all kinds, DST morning boundaries, ex-member chore, missed day."""
import sys; sys.path.insert(0, ".")
import tt; H = tt.H
from datetime import datetime, timezone, timedelta, date
from collections import Counter
H.fresh_db("ctt_push")
tt.install()
c = H.client()
import app.services.push_service as ps
sent = []
ps.send_to_users = lambda db, uids, b, household_id=None: (sent.append(b('de')['tag']), 1)[1]
hid, users, toks = H.household(["A", "B"]); A = H.auth(toks[0]); base = f"/api/households/{hid}"
s = H.session()
from app.models import Todo, TodoReminder, Pet, PetCareTask, Plant, PlantCareTask, Document, Chore, ChoreAssignment
import uuid
now = datetime(2026, 3, 29, 6, 30, tzinfo=timezone.utc)  # 08:30 CEST on DST-start day
t = Todo(household_id=hid, title="t"); s.add(t); s.flush()
s.add(TodoReminder(household_id=hid, todo_id=t.id, remind_at=now - timedelta(minutes=1)))
pet = Pet(household_id=hid, name="Rex", species="dog") if hasattr(Pet, "species") else Pet(household_id=hid, name="Rex"); s.add(pet); s.flush()
s.add(PetCareTask(household_id=hid, pet_id=pet.id, name="Wurm", interval_days=30, next_due_at=date(2026,3,29)))
pl = Plant(household_id=hid, name="Ficus"); s.add(pl); s.flush()
s.add(PlantCareTask(household_id=hid, plant_id=pl.id, care_type="water", interval_days=7, next_due_at=date(2026,3,29)))
ch = Chore(household_id=hid, title="Bad", recurrence="weekly", weekday=6, rotation_order=[str(users[0])], anchor_date=date(2026,3,29)); s.add(ch); s.flush()
CHID = ch.id
s.add(ChoreAssignment(household_id=hid, chore_id=ch.id, assigned_user_id=users[0], due_date=date(2026,3,29)))
try:
    s.add(Document(household_id=hid, title="Garantie", expiry_date=date(2026,3,29), uploaded_by_user_id=users[0]) if hasattr(Document, "uploaded_by_user_id") else Document(household_id=hid, title="Garantie", expiry_date=date(2026,3,29)))
    s.commit()
except Exception as e:
    s.rollback(); print("doc create failed:", str(e)[:200]); s.commit()
s.close()
tt.set_now(now)
def worker(i):
    db = H.session()
    try:
        return (ps.process_todo_reminders(db, now) + ps.process_pet_care_tasks(db, now) + ps.process_plant_care_tasks(db, now)
                + ps.process_chore_assignments(db, now) + ps.process_document_expiry(db, now))
    finally: db.close()
res = H.parallel(worker, 6)
print("6 parallel scheduler runs -> results:", res)
print("sent tags:", Counter(x.split('-')[0] for x in sent), "total", len(sent))

# DST end: 2026-10-25 local 07:59 CET (06:59Z) vs 08:00 (07:00Z)
sent.clear()
s = H.session(); s.add(ChoreAssignment(household_id=hid, chore_id=CHID, assigned_user_id=users[0], due_date=date(2026,10,25))); s.commit(); s.close()
for t_ in (datetime(2026,10,25,6,59,tzinfo=timezone.utc), datetime(2026,10,25,7,0,tzinfo=timezone.utc)):
    tt.set_now(t_); db = H.session(); n = ps.process_chore_assignments(db, t_); db.close(); print("DST-end", t_.isoformat(), "sent", n)

# Missed day: backend down whole due day -> next morning
sent.clear()
s = H.session(); print("11-01 assignment exists (materialised by scheduler on 10-25):", s.query(ChoreAssignment).filter_by(chore_id=CHID, due_date=date(2026,11,1)).count()); s.close()
t_ = datetime(2026,11,2,8,0,tzinfo=timezone.utc); db = H.session(); n = ps.process_chore_assignments(db, t_); db.close()
print("chore due 11-01, scheduler first runs 11-02 09:00 ->", n, "sent (dropped by design)")
