import os
import shutil
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.config import DATABASE_URL
from app.models import User
from app.auth import require_admin

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
    shutil.copy2(src, dest)

    size_kb = round(os.path.getsize(dest) / 1024, 2)
    return {
        "message": "تم إنشاء النسخة الاحتياطية بنجاح",
        "file": os.path.basename(dest),
        "size_kb": size_kb,
        "path": dest,
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
