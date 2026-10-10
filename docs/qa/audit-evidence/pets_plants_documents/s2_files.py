import sys, os, io; sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
W = os.path.dirname(os.path.abspath(__file__))
os.environ["UPLOAD_DIR"] = W + "/uploads"
os.environ["HOUSEHOLD_STORAGE_QUOTA_MB"] = "1"
import pgharness as H
H.fresh_db("ppd_files")
from fastapi.testclient import TestClient
from app.main import app
from collections import Counter
import datetime as dt
from PIL import Image
from app.models import StoredFile, DocumentFile, Document, Pet
hid, users, toks = H.household(["Anna","Ben","Carla"])
A, B, C = (H.auth(t) for t in toks)
F = f"/api/households/{hid}/files/"; D = f"/api/households/{hid}/documents/"
mk = lambda: TestClient(app, raise_server_exceptions=False)
c = mk()
def pdf(n=1000): return b"%PDF-1.4\n" + os.urandom(n)
def png():
    b = io.BytesIO(); Image.new("RGB",(20,20),(1,2,3)).save(b, "PNG"); return b.getvalue()
def up(data=None, mime="application/pdf", name="a.pdf", cl=None, h=A):
    return (cl or c).post(F, files={"file": (name, data or pdf(), mime)}, headers=h)

print("== F1 quota race: 1 MB quota, 8 parallel uploads of 200 KB ==")
res = H.parallel(lambda i: up(pdf(200_000), cl=mk()).status_code, 8)
used = c.get(D+"storage", headers=A).json()
print("statuses:", Counter(res), "used_bytes:", used["used_bytes"], "quota:", used["quota_bytes"], "exceeded:", used["used_bytes"] > used["quota_bytes"])
print("sequential upload now:", up(pdf(1000)).status_code)
s = H.session(); [s.delete(f) for f in s.query(StoredFile).all()]; s.commit(); s.close()

print("== F2 two documents claim the same file concurrently ==")
cnt = Counter()
for t in range(10):
    fid = up().json()["id"]
    res = H.parallel(lambda i: mk().post(D, json={"title": f"Doc{i}", "file_ids": [fid]}, headers=[A,B][i]).status_code, 2)
    cnt[tuple(sorted(res))] += 1
print(Counter(cnt))

print("== F3 pet photo PATCH and document create on the same image concurrently ==")
pet = c.post(f"/api/households/{hid}/pets/", json={"name":"Mia"}, headers=A).json()
cnt = Counter(); shared = 0
for t in range(15):
    fid = up(png(), "image/png", "p.png").json()["id"]
    def f(i):
        cl = mk()
        if i == 0: return cl.patch(f"/api/households/{hid}/pets/{pet['id']}", json={"photo_file_id": fid}, headers=A).status_code
        return cl.post(D, json={"title": "Scan", "file_ids": [fid]}, headers=B).status_code
    res = H.parallel(f, 2); cnt[tuple(res)] += 1
    s = H.session()
    p = s.get(Pet, pet["id"]); inDoc = s.query(DocumentFile).filter_by(file_id=fid).count()
    if p.photo_file_id is not None and str(p.photo_file_id) == fid and inDoc: shared += 1; shared_fid = fid
    s.close()
    c.patch(f"/api/households/{hid}/pets/{pet['id']}", json={"photo_file_id": None}, headers=A)
print("(pet PATCH, doc POST):", dict(cnt), "trials ending with file shared by pet AND document:", shared)
if shared:
    c.patch(f"/api/households/{hid}/pets/{pet['id']}", json={"photo_file_id": shared_fid}, headers=A)  # re-set (would 422 normally)
    s = H.session(); p = s.get(Pet, pet["id"]); p.photo_file_id = shared_fid; s.commit(); s.close()
    doc_id = H.session().query(DocumentFile).filter_by(file_id=shared_fid).first().document_id
    print("delete document ->", c.delete(f"{D}{doc_id}", headers=A).status_code)
    print("pet photo after doc delete:", c.get(f"/api/households/{hid}/pets/{pet['id']}", headers=A).json()["photo_file_id"])

print("== F4 orphan cleanup vs. late attach (interleaved manually, code of delete_orphan_files) ==")
from app.routers.files import remove_from_storage
fid = up().json()["id"]
s = H.session(); f = s.get(StoredFile, fid); f.created_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=25); s.commit(); s.close()
from app.routers import files as FR
s1 = H.session()
orig_all = None
# Step 1: cleanup selects orphans (same query as delete_orphan_files)
from sqlalchemy import exists
cutoff = dt.datetime.now(dt.timezone.utc) - FR.ORPHAN_FILE_GRACE
orphans = (s1.query(StoredFile).filter(StoredFile.created_at < cutoff)
    .filter(~s1.query(Pet.id).filter(Pet.photo_file_id == StoredFile.id).exists())
    .filter(~s1.query(FR.Plant.id).filter(FR.Plant.photo_file_id == StoredFile.id).exists())
    .filter(~s1.query(DocumentFile.file_id).filter(DocumentFile.file_id == StoredFile.id).exists()).all())
print("orphans selected:", [str(o.id)==fid for o in orphans])
# Step 2: user attaches the file to a new document (commits)
r = c.post(D, json={"title":"Mietvertrag", "file_ids":[fid]}, headers=A); print("attach:", r.status_code); doc_id = r.json()["id"]
# Step 3: cleanup deletes + commits
paths = [o.storage_path for o in orphans]
for o in orphans: s1.delete(o)
try:
    s1.commit(); print("cleanup commit OK")
except Exception as e:
    print("cleanup commit failed:", type(e).__name__); s1.rollback()
for p in paths: remove_from_storage(p)
r = c.get(f"{D}{doc_id}", headers=A); print("document after cleanup:", r.status_code, "files:", len(r.json().get("files", [])) if r.status_code==200 else r.text[:100])

print("== F5 removed member / outsider download ==")
fid = up(png(), "image/png", "p.png").json()["id"]
print("Carla download:", c.get(F+fid, headers=C).status_code)
print("Carla removed by admin:", c.delete(f"/api/households/{hid}/members/{users[2]}", headers=A).status_code)
print("Carla download after removal:", c.get(F+fid, headers=C).status_code)
hid2, u2, t2 = H.household(["Eve"]); E = H.auth(t2[0])
print("other household member using own hid path:", c.get(f"/api/households/{hid2}/files/{fid}", headers=E).status_code)
print("no token:", c.get(F+fid).status_code)
print("PDF headers:", (lambda r: (r.status_code, r.headers.get('content-disposition','')[:20], r.headers.get('x-content-type-options')))(c.get(F+up().json()['id'], headers=A)))

print("== F6 upload_document partial failure (2nd file invalid) ==")
s = H.session(); nfiles = s.query(StoredFile).filter_by(household_id=hid).count(); s.close()
ndisk = sum(len(fs) for _,_,fs in os.walk(W+"/uploads/"+str(hid)))
r = c.post(D+"upload", files=[("files", ("a.pdf", pdf(), "application/pdf")), ("files", ("b.pdf", b"notpdf", "application/pdf"))], data={"title":"X"}, headers=A)
s = H.session(); nfiles2 = s.query(StoredFile).filter_by(household_id=hid).count(); s.close()
ndisk2 = sum(len(fs) for _,_,fs in os.walk(W+"/uploads/"+str(hid)))
print("status", r.status_code, "db rows", nfiles, "->", nfiles2, "disk files", ndisk, "->", ndisk2)

print("== F7 delete document whose file also... / delete file in use ==")
fid = up().json()["id"]; doc = c.post(D, json={"title":"T","file_ids":[fid]}, headers=A).json()
print("DELETE /files on doc page:", c.delete(F+fid, headers=A).status_code)

print("== F8 expiry reset on date change ==")
s = H.session(); d = s.get(Document, doc["id"]); d.expiry_date = dt.date(2026,10,20); d.expiry_soon_notified_at = dt.datetime.now(dt.timezone.utc); s.commit(); s.close()
r = c.patch(D+doc["id"], json={"title":"T2"}, headers=A)
s = H.session(); print("title-only patch keeps soon flag:", s.get(Document, doc["id"]).expiry_soon_notified_at is not None); s.close()
c.patch(D+doc["id"], json={"expiry_date":"2026-11-30"}, headers=A)
s = H.session(); print("expiry change resets soon flag:", s.get(Document, doc["id"]).expiry_soon_notified_at is None); s.close()

print("== F9 household deletion removes files on disk ==")
hid3, u3, t3 = H.household(["Solo"]); S3 = H.auth(t3[0])
c.post(f"/api/households/{hid3}/files/", files={"file": ("a.pdf", pdf(), "application/pdf")}, headers=S3)
print("dir exists before:", os.path.isdir(W+"/uploads/"+str(hid3)))
print("leave:", c.post(f"/api/households/{hid3}/leave", headers=S3).status_code, "dir exists after:", os.path.isdir(W+"/uploads/"+str(hid3)))
