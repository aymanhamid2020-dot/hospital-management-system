# -*- coding: utf-8 -*-
"""جدولة النسخ الاحتياطي والوجهات: حساب المواعيد + تقليم مستقل لكل خطة
+ حذف نسخة مفردة + واجهة الإدارة (CRUD) وحجب المفاتيح السرّية.

تُعزل النسخ الفعلية في مجلد مؤقت (bdir) فلا تلوّث backups/ الحقيقية،
وكذلك ``backup_dir`` في اختبار تشغيل الخطة.
"""
import os
import sqlite3
from datetime import datetime
from types import SimpleNamespace

import pytest

from app import tasks as tasks_mod
from app.routers import backup as backup_mod


# ================= أدوات =================
def _sched(**kw):
    base = dict(name="خطة", frequency="daily", enabled=True, hour=3, minute=0,
                weekday=0, monthday=1, year_month=1, year_day=1, keep=7)
    base.update(kw)
    return SimpleNamespace(**base)


def _mk(d, name):
    path = os.path.join(d, name)
    con = sqlite3.connect(path)
    try:
        con.execute("CREATE TABLE t (v TEXT)")
        con.commit()
    finally:
        con.close()
    return path


@pytest.fixture()
def bdir(tmp_path, monkeypatch):
    d = tmp_path / "backups"
    d.mkdir()
    monkeypatch.setattr(backup_mod, "BACKUP_DIR", str(d))
    return str(d)


# ================= حساب الموعد التالي =================
def test_next_run_daily_before_and_after_window():
    s = _sched(hour=3, minute=0)
    # قبل نافذة التنفيذ ⇒ اليوم نفسه
    assert tasks_mod.compute_next_run(s, datetime(2026, 9, 27, 2, 0)) == \
        datetime(2026, 9, 27, 3, 0)
    # بعد النافذة ⇒ الغد
    assert tasks_mod.compute_next_run(s, datetime(2026, 9, 27, 4, 0)) == \
        datetime(2026, 9, 28, 3, 0)


def test_next_run_weekly_maps_sunday_based_calendar():
    """0=الأحد في تقويم الخطة ⇐ 6 في تقويم بايثون — لكل الأيام السبعة."""
    now = datetime(2026, 9, 27, 10, 0)
    for my_wd in range(7):
        row = _sched(frequency="weekly", weekday=my_wd, hour=3)
        got = tasks_mod.compute_next_run(row, now)
        assert got > now, my_wd
        assert got.weekday() == (my_wd + 6) % 7, my_wd
        assert (got.hour, got.minute) == (3, 0)


def test_next_run_weekly_never_returns_past():
    """يوم التنفيذ نفسه بعد انقضاء وقته ⇒ الأسبوع القادم لا الأمس."""
    s = _sched(frequency="weekly", weekday=0, hour=3)
    # ابحث عن أحد ماضٍ على الأقل بيوم لتغطية الحالتين
    now = datetime(2026, 9, 27, 23, 59)
    got = tasks_mod.compute_next_run(s, now)
    assert got > now
    assert got.weekday() == 6


def test_next_run_monthly_clamps_to_short_months():
    """31 في فبراير ⇒ آخر يوم منه (28) لا تمرير الشهر."""
    s = _sched(frequency="monthly", monthday=31, hour=3)
    got = tasks_mod.compute_next_run(s, datetime(2026, 2, 27, 4, 0))
    assert (got.year, got.month, got.day) == (2026, 2, 28)
    # وعبور الشهر بسلاسة
    got2 = tasks_mod.compute_next_run(s, datetime(2026, 1, 31, 4, 0))
    assert (got2.year, got2.month, got2.day) == (2026, 2, 28)


def test_next_run_yearly_rolls_over():
    s = _sched(frequency="yearly", year_month=6, year_day=10, hour=3)
    # قبل التاريخ المستهدف ⇒ هذا العام
    got = tasks_mod.compute_next_run(s, datetime(2026, 6, 1, 0, 0))
    assert (got.year, got.month, got.day) == (2026, 6, 10)
    # بعده ⇒ السنة القادمة
    got2 = tasks_mod.compute_next_run(s, datetime(2026, 6, 11, 0, 0))
    assert (got2.year, got2.month, got2.day) == (2027, 6, 10)


def test_next_run_yearly_29_feb_rolls_past_non_leap_year():
    s = _sched(frequency="yearly", year_month=2, year_day=29, hour=3)
    got = tasks_mod.compute_next_run(s, datetime(2026, 3, 1, 0, 0))
    assert (got.month, got.day) == (2, 28)   # 2026 سنة غير كبيسة
    assert got > datetime(2026, 3, 1, 0, 0)


# ================= تقليم مستقل لكل خطة =================
def test_prune_prefix_keeps_only_its_own_plan(tmp_path):
    d = str(tmp_path)
    for i in range(1, 6):
        _mk(d, f"sched1_2026010{i}_000000.db")
        _mk(d, f"sched2_2026010{i}_000000.db")
    _mk(d, "hospital_20260101_000000.db")

    deleted = tasks_mod._prune_prefix(d, "sched1_", keep=2)
    left = sorted(os.listdir(d))

    assert len(deleted) == 3
    assert sum(n.startswith("sched1_") for n in left) == 2
    # الخطة الثانية وبقية البادئات لم تُمسّ إطلاقًا
    assert sum(n.startswith("sched2_") for n in left) == 5
    assert sum(n.startswith("hospital_") for n in left) == 1
    assert "sched1_20260105_000000.db" in left   # الأحدث بقيت
    assert "sched1_20260101_000000.db" not in left


def test_global_prune_leaves_sched_files_alone(tmp_path):
    """prune_backups لا تنظّف sched* — تلك مسؤولية خطةها وحدها."""
    d = str(tmp_path)
    _mk(d, "hospital_20260101_000000.db")
    _mk(d, "auto_20260101_000000.db")
    _mk(d, "sched1_20260101_000000.db")
    tasks_mod.prune_backups(d, keep=1)
    assert "sched1_20260101_000000.db" in os.listdir(d)


def test_prune_keeps_oldest_by_mtime_not_lexical_name(tmp_path):
    """فرز بالاسم يكذب: اسمٌ يسبق غيره رقميًّا لا يعني أنه الأحدث.

    كان ``hospital_zzz_…`` يُعامَل كأنه الأحدث لسبقه حرف z حرف 2 في الفرز
    التنازلي، فتُحذف نسخة أحدث ويُبقي ملف قديم — عكس سياسة الاحتفاظ.
    """
    d = str(tmp_path)
    older = _mk(d, "hospital_zzz_name_sorts_first_but_is_old.db")
    newer = _mk(d, "hospital_20260101_000000.db")
    os.utime(older, (1000000000, 1000000000))   # 2001-09-09
    os.utime(newer, (2000000000, 2000000000))   # 2033-05-18

    deleted = tasks_mod.prune_backups(d, keep=1)

    assert deleted == ["hospital_zzz_name_sorts_first_but_is_old.db"]
    assert os.listdir(d) == ["hospital_20260101_000000.db"]


# ================= تشغيل الخطة فعليًا =================
def test_run_schedule_now_creates_and_prunes_per_plan(tmp_path, monkeypatch):
    from app.database import SessionLocal

    src = tmp_path / "src.db"
    con = sqlite3.connect(str(src))
    con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    con.commit()
    con.close()
    monkeypatch.setattr(tasks_mod, "_sqlite_db_path", lambda: str(src))

    out = tmp_path / "backups"
    row = _sched(id=1, name="اليومية", keep=2)

    db = SessionLocal()
    try:
        for i in range(5):   # خمس نسخ متتالية ⇒ تبقى آخر 2
            tasks_mod.run_schedule_now(
                row, db, now=datetime(2026, 1, 1, 3, i), backup_dir=str(out))
        left = sorted(os.listdir(str(out)))
        assert len(left) == 2
        assert all(n.startswith("sched1_") for n in left)
        assert left[-1] == "sched1_20260101_030400.db"
        assert row.last_file == "sched1_20260101_030400.db"
        assert row.last_run_at == datetime(2026, 1, 1, 3, 4)
        assert "وجهة" in (row.last_result or "")
        assert src.exists()   # المصدر لم يُمسّ
    finally:
        db.close()


def test_run_schedule_now_reports_missing_sqlite(monkeypatch):
    from app.database import SessionLocal
    monkeypatch.setattr(tasks_mod, "_sqlite_db_path", lambda: None)
    row = _sched(id=9, name="سنوية")
    db = SessionLocal()
    try:
        res = tasks_mod.run_schedule_now(row, db, backup_dir="/tmp/none")
        assert res["file"] is None
        assert "SQLite" in row.last_result
    finally:
        db.close()


# ================= واجهة الإدارة =================
def test_new_endpoints_require_admin(client):
    for path, method in (("/backup/schedules", client.get),
                         ("/backup/schedules", client.post),
                         ("/backup/destinations", client.get),
                         ("/backup/destinations", client.post),
                         ("/backup/hospital_x.db", client.delete)):
        r = method(path)
        assert r.status_code in (401, 403), f"{path} → {r.status_code}"


def test_schedule_crud_sets_next_run(client, admin):
    r = client.post("/backup/schedules", headers=admin,
                    json={"name": "اليومية", "frequency": "daily",
                          "hour": 3, "keep": 5})
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["next_run_at"] is not None
    assert row["frequency_ar"] == "يومية"
    sid = row["id"]

    r2 = client.put(f"/backup/schedules/{sid}", headers=admin,
                    json={"name": "الأسبوعية", "frequency": "weekly",
                          "weekday": 5, "hour": 1, "keep": 3})
    assert r2.status_code == 200, r2.text
    assert r2.json()["frequency"] == "weekly"
    assert r2.json()["keep"] == 3
    assert r2.json()["next_run_at"] is not None

    idx = client.get("/backup/schedules", headers=admin).json()
    assert any(x["id"] == sid for x in idx)

    assert client.delete(f"/backup/schedules/{sid}", headers=admin).status_code == 200
    assert all(x["id"] != sid
               for x in client.get("/backup/schedules", headers=admin).json())


def test_schedule_rejects_unknown_frequency(client, admin):
    r = client.post("/backup/schedules", headers=admin,
                    json={"name": "ساعية", "frequency": "hourly"})
    assert r.status_code == 400
    r2 = client.post("/backup/schedules", headers=admin,
                     json={"name": "س", "frequency": "daily", "hour": 99})
    assert r2.status_code == 422   # حدود pydantic


def test_schedule_all_four_frequencies_accepted(client, admin):
    ids = []
    for freq in ("daily", "weekly", "monthly", "yearly"):
        r = client.post("/backup/schedules", headers=admin,
                        json={"name": f"خطة {freq}", "frequency": freq})
        assert r.status_code == 200, r.text
        assert r.json()["next_run_at"] is not None
        ids.append(r.json()["id"])
    for i in ids:
        assert client.delete(f"/backup/schedules/{i}", headers=admin).status_code == 200


def test_destination_masks_secrets_and_keeps_stored_values(client, admin):
    r = client.post("/backup/destinations", headers=admin,
                    json={"name": "جوجل", "kind": "gdrive", "enabled": True,
                          "config": {"client_id": "id1",
                                     "client_secret": "s3cr3t",
                                     "refresh_token": "rt1"}})
    assert r.status_code == 200, r.text
    got = r.json()
    did = got["id"]
    # المفاتيح السرّية مقنَّعة — وغير السرّية بائن
    assert got["config"]["client_secret"] == "•••"
    assert got["config"]["refresh_token"] == "•••"
    assert got["config"]["client_id"] == "id1"

    try:
        # تعديل بإرجاع القيم المقنَّعة ⇒ لا تُفرَّغ المفاتيح المخزَّنة
        r2 = client.put(f"/backup/destinations/{did}", headers=admin,
                        json={"name": "جوجل", "kind": "gdrive", "enabled": False,
                              "config": {"client_id": "id1",
                                         "client_secret": "•••",
                                         "refresh_token": "•••"}})
        assert r2.status_code == 200, r2.text

        from app.database import SessionLocal
        from app.models import BackupDestination
        db = SessionLocal()
        try:
            stored = db.get(BackupDestination, did)
            assert stored.config["client_secret"] == "s3cr3t"
            assert stored.config["refresh_token"] == "rt1"
            assert stored.enabled is False
        finally:
            db.close()
    finally:
        assert client.delete(f"/backup/destinations/{did}",
                             headers=admin).status_code == 200


def test_destination_rejects_unknown_kind(client, admin):
    r = client.post("/backup/destinations", headers=admin,
                    json={"name": "غريب", "kind": "ftp"})
    assert r.status_code == 400


def test_destination_update_and_delete(client, admin):
    r = client.post("/backup/destinations", headers=admin,
                    json={"name": "مجلد خارجي", "kind": "local",
                          "config": {"path": "/tmp/x"}})
    assert r.status_code == 200, r.text
    did = r.json()["id"]
    r2 = client.put(f"/backup/destinations/{did}", headers=admin,
                    json={"name": "مجلد خارجي", "kind": "local",
                          "enabled": True, "keep": 4, "config": {"path": "/tmp/y"}})
    assert r2.status_code == 200
    assert r2.json()["keep"] == 4
    assert client.delete(f"/backup/destinations/{did}",
                         headers=admin).status_code == 200
    assert client.delete(f"/backup/destinations/{did}",
                         headers=admin).status_code == 404


# ================= حذف نسخة مفردة =================
def test_delete_single_backup(bdir, client, admin):
    path = _mk(bdir, "hospital_20260101_000000.db")
    r = client.delete("/backup/hospital_20260101_000000.db", headers=admin)
    assert r.status_code == 200, r.text
    assert not os.path.exists(path)
    # تكرار الحذف ⇒ 404
    assert client.delete("/backup/hospital_20260101_000000.db",
                         headers=admin).status_code == 404


def test_delete_backup_guards_traversal_and_non_db(bdir, client, admin):
    with open(os.path.join(bdir, "notes.txt"), "w", encoding="utf-8") as fh:
        fh.write("x")
    # ملف ليس نسخة
    assert client.delete("/backup/notes.txt", headers=admin).status_code == 400
    # اجتياز مسار (كشف .. قبل أي شيء)
    r = client.delete("/backup/..%2Fmain.py", headers=admin)
    assert r.status_code in (400, 404), r.status_code


def test_delete_backup_leaves_others(bdir, client, admin):
    keep = _mk(bdir, "auto_20260102_000000.db")
    gone = _mk(bdir, "hospital_20260101_000000.db")
    assert client.delete("/backup/hospital_20260101_000000.db",
                         headers=admin).status_code == 200
    assert os.path.exists(keep)
    assert not os.path.exists(gone)


# ================= الدفع إلى الوجهات =================
def test_manual_backup_reports_push(bdir, client, admin):
    """إنشاء نسخة يعيد تقرير الدفع — بلا وجهات مفعّلة ⇒ قائمة فارغة."""
    r = client.post("/backup", headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "push" in body
    assert body["push"] == []
    assert body["file"].startswith("hospital_")
    assert os.path.isfile(os.path.join(bdir, body["file"]))


def test_push_to_local_destination_and_prune(tmp_path):
    """وجهة محلية: تُستلم النسخة ثم يُبقي آخر keep على الوجهة."""
    from app import backup_sync
    from app.database import SessionLocal
    from app.models import BackupDestination

    target = tmp_path / "offsite"
    src = tmp_path / "src"
    src.mkdir()

    db = SessionLocal()
    dest_id = None
    try:
        dest = BackupDestination(name="مجلد خارجي", kind="local", enabled=True,
                                 config={"path": str(target)}, keep=2)
        db.add(dest)
        db.commit()
        dest_id = dest.id

        for i in range(4):
            f = src / f"auto_2026010{i}_000000.db"
            f.write_text("x", encoding="utf-8")
            report = backup_sync.push_to_destinations(db, str(f))
            assert report[0]["ok"], report
            assert report[0]["name"] == "مجلد خارجي"

        kept = sorted(os.listdir(str(target)))
        assert len(kept) == 2            # keep=2 طبّق على الوجهة
        assert kept[-1] == "auto_20260103_000000.db"

        # صفّ الوجهة حفظ آخر مزامنة ولاحذف خطأ
        row = db.get(BackupDestination, dest_id)
        assert row.last_sync_at is not None
        assert row.last_error is None
        assert row.last_file == "auto_20260103_000000.db"
    finally:
        if dest_id is not None:
            db.delete(db.get(BackupDestination, dest_id))
            db.commit()
        db.close()


def test_upload_reports_missing_source_and_unknown_kind(tmp_path):
    from app import backup_sync
    ok, msg = backup_sync.upload("local", {"path": str(tmp_path)},
                                 str(tmp_path / "nope.db"))
    assert not ok and "غير موجود" in msg

    ok2, msg2 = backup_sync.upload("ftp", {}, "x.db")
    assert not ok2 and "غير مدعوم" in msg2


def test_test_connection_local(tmp_path):
    from app import backup_sync
    ok, msg = backup_sync.test_connection("local", {"path": str(tmp_path / "d")})
    assert ok, msg
    ok2, msg2 = backup_sync.test_connection("local", {})
    assert not ok2 and "ناقصة" in msg2
