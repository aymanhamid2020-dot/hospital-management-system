import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.config import DATABASE_URL
from app.models import User
from app.auth import require_admin
from app.tasks import prune_backups

router = APIRouter(prefix="/backup", tags=["Backup"])

BACKUP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backups")


def _db_file_path() -> str:
    """استخراج مسار ملف SQLite من رابط قاعدة البيانات."""
    if not DATABASE_URL.startswith("sqlite:///"):
        raise HTTPException(status_code=400, detail="النسخ الاحتياطي متاح لقاعدة SQLite فقط")
    return DATABASE_URL.replace("sqlite:///", "")


@router.post("", summary="إنشاء نسخة احتياطية")
async def create_backup(_: User = Depends(require_admin)):
    """نسخ ملف قاعدة البيانات إلى مجلد backups (للمدير فقط)"""
    src = _db_file_path()
    if not os.path.exists(src):
        raise HTTPException(status_code=404, detail="ملف قاعدة البيانات غير موجود")

    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"hospital_{timestamp}.db")
    # نسخ متسق عبر sqlite backup API — shutil.copy مع WAL يلتقط ملفًا
    # غير متسق (الم transactions في hospital.db-wal) فيرفضه quick_check عند الاستعادة
    import sqlite3
    src_con = sqlite3.connect(src, timeout=10)
    try:
        dest_con = sqlite3.connect(dest)
        try:
            src_con.backup(dest_con)
        finally:
            dest_con.close()
    finally:
        src_con.close()

    size_kb = round(os.path.getsize(dest) / 1024, 2)
    # تقليم فوري حسب السياسة — يمنع تكدّس hospital_* بتكرار الفحوصات
    pruned = prune_backups(BACKUP_DIR)
    return {
        "message": "تم إنشاء النسخة الاحتياطية بنجاح",
        "file": os.path.basename(dest),
        "size_kb": size_kb,
        "path": dest,
        "pruned": len(pruned),
    }


@router.get("", summary="قائمة النسخ الاحتياطية")
async def list_backups(_: User = Depends(require_admin)):
    """عرض كل النسخ الاحتياطية المتاحة"""
    if not os.path.isdir(BACKUP_DIR):
        return []
    files = []
    for name in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if name.endswith(".db"):
            full = os.path.join(BACKUP_DIR, name)
            files.append({
                "file": name,
                "size_kb": round(os.path.getsize(full) / 1024, 2),
                "created_at": datetime.fromtimestamp(os.path.getmtime(full)).isoformat(),
                "restorable": name.endswith(".db"),
            })
    return files


@router.get("/status", summary="حالة مجلد النسخ")
async def backup_status(_: User = Depends(require_admin)):
    """إحصاءة فعلية لمجلد النسخ: العدد والأحجام والأقدم/الأحدث والسياسة والقرص."""
    import shutil

    files = []
    if os.path.isdir(BACKUP_DIR):
        for n in os.listdir(BACKUP_DIR):
            if not n.endswith(".db"):
                continue
            full = os.path.join(BACKUP_DIR, n)
            try:
                files.append((n, os.path.getsize(full), os.path.getmtime(full)))
            except OSError:
                continue
    files.sort(key=lambda f: f[2])  # الأقدم → الأحدث
    total = sum(f[1] for f in files)
    by_kind = {"hospital": 0, "auto": 0, "other": 0}
    for n, _, _ in files:
        if n.startswith("auto_"):
            by_kind["auto"] += 1
        elif n.startswith("hospital_"):
            by_kind["hospital"] += 1
        else:
            by_kind["other"] += 1
    try:
        target = BACKUP_DIR if os.path.isdir(BACKUP_DIR) else os.getcwd()
        free_mb = round(shutil.disk_usage(target).free / (1024 * 1024), 1)
    except OSError:
        free_mb = None
    return {
        "dir": BACKUP_DIR,
        "files": len(files),
        "by_kind": by_kind,
        "total_mb": round(total / (1024 * 1024), 2),
        "oldest": {"file": files[0][0],
                   "created_at": datetime.fromtimestamp(files[0][2]).isoformat()}
                  if files else None,
        "newest": {"file": files[-1][0],
                   "created_at": datetime.fromtimestamp(files[-1][2]).isoformat()}
                  if files else None,
        "retention": int(os.getenv("BACKUP_RETENTION", "7")),
        "interval_hours": float(os.getenv("BACKUP_INTERVAL_HOURS", "24")),
        "disk_free_mb": free_mb,
    }


@router.get("/verify", summary="فحص سلامة النسخ")
async def verify_backups(
    limit: int = Query(20, ge=1, le=100),
    deep: bool = Query(False),
    _: User = Depends(require_admin),
):
    """quick_check على أحدث نسخ (deep=1 → integrity_check الأعمق) — قراءة فقط.

    يعيد لكل ملف: سليم/تالف + رسالة الخطأ + عدد مستخدمي القاعدة (مؤشر تدفقي).
    """
    import sqlite3

    if not os.path.isdir(BACKUP_DIR):
        return {"checked": 0, "ok": 0, "bad": [], "results": [], "deep": deep}
    cands = []
    for n in os.listdir(BACKUP_DIR):
        if not n.endswith(".db"):
            continue
        full = os.path.join(BACKUP_DIR, n)
        try:
            cands.append((os.path.getmtime(full), n, full))
        except OSError:
            continue
    cands.sort(reverse=True)  # الأحدث أولًا
    results = []
    for _, n, full in cands[:limit]:
        item = {"file": n, "ok": False, "error": None, "users": None}
        try:
            # فتح للقراءة فقط حتى لا يعدّل الفحص الملف ولا ينشئ journals
            con = sqlite3.connect(f"file:{full}?mode=ro", uri=True, timeout=5)
            try:
                row = con.execute(
                    "PRAGMA integrity_check" if deep else "PRAGMA quick_check"
                ).fetchone()
                item["ok"] = bool(row and row[0] == "ok")
                if not item["ok"]:
                    item["error"] = row[0] if row else "لا نتيجة من الفحص"
                try:
                    u = con.execute("SELECT count(*) FROM users").fetchone()
                    item["users"] = u[0] if u else 0
                except Exception:
                    item["users"] = None
            finally:
                con.close()
        except Exception as exc:  # ملف تالف فعلًا أو ليس SQLite
            item["error"] = f"{type(exc).__name__}: {exc}"
        results.append(item)
    bad = [r for r in results if not r["ok"]]
    return {"checked": len(results), "ok": len(results) - len(bad),
            "bad": bad, "results": results, "deep": deep}


@router.post("/prune", summary="تنظيف النسخ الزائدة")
async def prune_now(
    keep: int | None = Query(None, ge=1, le=1000),
    _: User = Depends(require_admin),
):
    """تطبيق سياسة الاحتفاظ فورًا (keep اختياري — وإلا BACKUP_RETENTION)."""
    if not os.path.isdir(BACKUP_DIR):
        return {"message": "لا يوجد مجلد نسخ بعد", "deleted": [],
                "files_remaining": 0, "retention": None}
    deleted = prune_backups(BACKUP_DIR, keep)
    remaining = sum(1 for n in os.listdir(BACKUP_DIR) if n.endswith(".db"))
    eff = keep if keep is not None else int(os.getenv("BACKUP_RETENTION", "7"))
    return {"message": f"حُذف {len(deleted)} نسخة زائدة (الاحتفاظ بآخر {eff} لكل نوع)",
            "deleted": deleted, "files_remaining": remaining, "retention": eff}


@router.get("/{filename}", summary="تنزيل نسخة احتياطية")
async def download_backup(filename: str, _: User = Depends(require_admin)):
    """تنزيل ملف نسخة احتياطية محددة"""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="اسم ملف غير صالح")
    path = os.path.join(BACKUP_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="النسخة الاحتياطية غير موجودة")
    return FileResponse(path, media_type="application/octet-stream", filename=filename)


@router.post("/{filename}/restore", summary="استعادة نسخة احتياطية")
async def restore_backup(filename: str, _: User = Depends(require_admin)):
    """استعادة قاعدة البيانات من نسخة SQLite (للمدير فقط).

    تتحقق صلاحية الملف أولًا (قاعدة SQLite سليمة بها جدول users)، ثم تصنع
    نسخة أمان تلقائية قبل الاستبدال، ثم تنسخ محتوى النسخة إلى ملف القاعدة
    الحي عبر sqlite backup API. على PostgreSQL: 400 (استخدم pg_restore).
    """
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="اسم ملف غير صالح")
    src_db = _db_file_path()  # يرفع 400 على PostgreSQL
    path = os.path.join(BACKUP_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="النسخة الاحتياطية غير موجودة")
    if not filename.endswith(".db"):
        raise HTTPException(status_code=400, detail="الاستعادة تتطلب ملف ‎.db‎ صالحًا")

    # التحقق: الملف قاعدة SQLite سليمة بها جدول المستخدمين
    import sqlite3
    try:
        con = sqlite3.connect(path, timeout=10)
        try:
            has_users = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
            ).fetchone()
            check = con.execute("PRAGMA quick_check").fetchone()
        finally:
            con.close()
    except Exception:
        raise HTTPException(status_code=400, detail="الملف ليس قاعدة SQLite صالحة")
    if not has_users or not check or check[0] != "ok":
        raise HTTPException(status_code=400,
                            detail="الملف ليس نسخة صحيحة لهذه القاعدة")

    # نسخة أمان قبل الاستبدال — لا استعادة إن فشلت
    # (بالمجلد نفسه BACKUP_DIR لتظهر في قائمة /backup)
    from app.tasks import create_auto_backup
    safety = create_auto_backup(backup_dir=BACKUP_DIR)
    if not safety:
        raise HTTPException(status_code=500,
                            detail="تعذّرت نسخة الأمان — لم تُستعد النسخة")

    # إغلاق اتصالات ORM ثم نسخ محتوى النسخة إلى ملف القاعدة الحي
    from app.database import engine
    engine.dispose()
    src_con = sqlite3.connect(path, timeout=10)
    dst_con = sqlite3.connect(src_db, timeout=10)
    try:
        src_con.backup(dst_con)
    finally:
        dst_con.close()
        src_con.close()

    return {
        "message": "تمت استعادة قاعدة البيانات بنجاح",
        "restored": filename,
        "safety_copy": os.path.basename(safety),
    }
