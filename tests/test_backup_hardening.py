# -*- coding: utf-8 -*-
"""بند صلابة النسخ الاحتياطي: تقليم موحّد + فحص سلامة + حالة فعلية.

تعزل الاختبارات BACKUP_DIR إلى مجلد مؤقت (tmp_path) فلا تلوّث backups/ الحقيقية.
"""
import os
import sqlite3

import pytest

from app import tasks as tasks_mod
from app.routers import backup as backup_mod


@pytest.fixture()
def bdir(tmp_path, monkeypatch):
    d = tmp_path / "backups"
    d.mkdir()
    monkeypatch.setattr(backup_mod, "BACKUP_DIR", str(d))
    return str(d)


def _make(d, name, kind="valid_users"):
    """ملف نسخة مزيّف: قاعدة SQLite صالحة (بجدول users أو بغيره) أو قمامة."""
    path = os.path.join(d, name)
    if kind == "garbage":
        with open(path, "wb") as fh:
            fh.write(b"not a sqlite database at all")
        return path
    con = sqlite3.connect(path)
    try:
        con.execute("CREATE TABLE t (v TEXT)")
        con.execute("INSERT INTO t VALUES ('x')")
        if kind == "valid_users":
            con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, u TEXT)")
            con.execute("INSERT INTO users VALUES (1, 'admin')")
        con.commit()
    finally:
        con.close()
    return path


# ================= التقليم الموحّد =================
def test_prune_keeps_last_per_prefix(bdir):
    """الاحتفاظ بآخر N من كل بادئة + عدم مسّ بقية الملفات."""
    for i in range(1, 6):
        _make(bdir, f"hospital_2026010{i}_000000.db")
        _make(bdir, f"auto_2026010{i}_000000.db")
    _make(bdir, "_test_keepme.db")  # بادئة أخرى = مقدّس
    with open(os.path.join(bdir, "notes.txt"), "w") as fh:
        fh.write("x")

    deleted = tasks_mod.prune_backups(bdir, keep=2)

    left = sorted(os.listdir(bdir))
    assert len(deleted) == 6  # 3 hospital + 3 auto
    assert sum(n.startswith("hospital_") for n in left) == 2
    assert sum(n.startswith("auto_") for n in left) == 2
    assert "_test_keepme.db" in left and "notes.txt" in left
    # الأحدث هي المحفوظة
    assert "hospital_20260105_000000.db" in left
    assert "hospital_20260101_000000.db" not in left


def test_prune_reads_env_retention(bdir, monkeypatch):
    """keep=None يقرأ BACKUP_RETENTION وقت الاستدعاء."""
    monkeypatch.setenv("BACKUP_RETENTION", "1")
    _make(bdir, "hospital_20260101_000000.db")
    _make(bdir, "hospital_20260102_000000.db")
    deleted = tasks_mod.prune_backups(bdir)
    assert len(deleted) == 1
    assert os.listdir(bdir) == ["hospital_20260102_000000.db"]


def test_prune_missing_dir_is_noop(tmp_path):
    assert tasks_mod.prune_backups(str(tmp_path / "nope"), keep=3) == []


# ================= الإنشاء يقلّص فورًا =================
def test_create_backup_trims_manual_pile(bdir, client, admin, monkeypatch):
    """POST /backup يطبّق السياسة فورًا ويبلغ عن المحذوف."""
    monkeypatch.setenv("BACKUP_RETENTION", "2")
    for i in range(1, 5):
        _make(bdir, f"hospital_2026010{i}_000000.db")

    r = client.post("/backup", headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "pruned" in body and body["pruned"] >= 3
    hospital = [n for n in os.listdir(bdir) if n.startswith("hospital_")]
    assert len(hospital) == 2
    # المُنشأ للتوّ بقي (الأحدث)
    assert body["file"] in hospital


def test_created_backup_lands_in_isolated_dir(bdir, client, admin):
    """عزل BACKUP_DIR يعمل: لا يُنشأ شيء في backups/ الحقيقية."""
    repo_dir = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(backup_mod.__file__))), "backups")
    before = set(os.listdir(repo_dir)) if os.path.isdir(repo_dir) else set()
    r = client.post("/backup", headers=admin)
    assert r.status_code == 200
    assert r.json()["file"] in os.listdir(bdir)
    after = set(os.listdir(repo_dir)) if os.path.isdir(repo_dir) else set()
    assert after == before


# ================= الحالة =================
def test_status_reports_real_state(bdir, client, admin):
    _make(bdir, "hospital_20260101_000000.db")
    _make(bdir, "hospital_20260102_000000.db")
    _make(bdir, "auto_20260103_000000.db")

    r = client.get("/backup/status", headers=admin)
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["files"] == 3
    assert st["by_kind"] == {"hospital": 2, "auto": 1, "other": 0}
    assert st["total_mb"] > 0
    assert st["oldest"]["file"] == "hospital_20260101_000000.db"
    assert st["newest"]["file"] == "auto_20260103_000000.db"
    assert st["retention"] >= 1 and st["interval_hours"] > 0
    assert st["disk_free_mb"] is None or st["disk_free_mb"] > 0
    assert st["dir"] == bdir


def test_backup_admin_endpoints_require_auth(client):
    for path, method in (("/backup/status", client.get),
                         ("/backup/verify", client.get),
                         ("/backup/prune", client.post)):
        assert method(path).status_code in (401, 403), path


# ================= فحص السلامة =================
def test_verify_passes_good_files(bdir, client, admin):
    _make(bdir, "hospital_20260101_000000.db")
    _make(bdir, "auto_20260102_000000.db", kind="valid")  # بلا users
    r = client.get("/backup/verify", headers=admin)
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["checked"] == 2 and v["ok"] == 2 and v["bad"] == []
    by_name = {x["file"]: x for x in v["results"]}
    assert by_name["hospital_20260101_000000.db"]["users"] == 1
    assert by_name["auto_20260102_000000.db"]["users"] is None  # لا جدول users


def test_verify_flags_garbage_quick_and_deep(bdir, client, admin):
    _make(bdir, "hospital_20260101_000000.db")
    _make(bdir, "hospital_20260109_000000.db", kind="garbage")
    v = client.get("/backup/verify", headers=admin).json()
    assert v["ok"] == 1 and len(v["bad"]) == 1
    assert v["bad"][0]["file"] == "hospital_20260109_000000.db"
    assert v["bad"][0]["error"]
    v2 = client.get("/backup/verify?deep=true", headers=admin).json()
    assert len(v2["bad"]) == 1 and v2["deep"] is True


def test_verify_limit_checks_newest_only(bdir, client, admin):
    _make(bdir, "hospital_20260101_000000.db", kind="garbage")  # قديم تالف
    _make(bdir, "hospital_20260109_000000.db")                  # حديث سليم
    v = client.get("/backup/verify?limit=1", headers=admin).json()
    assert v["checked"] == 1 and v["ok"] == 1 and v["bad"] == []
    assert v["results"][0]["file"] == "hospital_20260109_000000.db"


def test_verify_rejects_bad_limit(bdir, client, admin):
    assert client.get("/backup/verify?limit=0",
                      headers=admin).status_code == 422


# ================= تنظيف يدوي =================
def test_prune_endpoint_deletes_and_reports(bdir, client, admin):
    for i in range(1, 6):
        _make(bdir, f"hospital_2026010{i}_000000.db")
    r = client.post("/backup/prune?keep=2", headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["deleted"]) == 3
    assert body["files_remaining"] == 2
    assert body["retention"] == 2
    assert "حُذف" in body["message"]  # رسالة عربية


def test_download_route_still_wins_over_status(bdir, client, admin):
    """ترتيب المسارات: تنزيل اسم ملف عادي لا يبتلع بمسار status/verify."""
    _make(bdir, "hospital_20260101_000000.db")
    r = client.get("/backup/hospital_20260101_000000.db", headers=admin)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/octet-stream")
    assert client.get("/backup/status", headers=admin).json()["files"] == 1
