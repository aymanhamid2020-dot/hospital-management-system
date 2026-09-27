# -*- coding: utf-8 -*-
"""رفع النسخ الاحتياطية إلى وجهات التخزين: مجلد محلي أو سحابة.

الأنواع المدعومة ومتطلبات كلٍّ منها:

======== ==========================================================
Kind     مفاتيح ``config`` المطلوبة
======== ==========================================================
local    ``path`` — مجلد النسخ على القرص
gdrive   ``client_id`` + ``client_secret`` + ``refresh_token``
         (+ اختياري ``folder_id`` لمجلد محدَّد)
onedrive ``client_id`` + ``refresh_token`` (+ اختياري ``client_secret``
         و ``folder`` مسار داخل OneDrive)
webdav   ``url`` + ``username`` + ``password``
http     ``url`` (+ اختياري ``token`` يُرسل كـ Authorization)
======== ==========================================================

كل الدوال تُرجع ``(نجاح: bool, رسالة: str)`` ولا ترمي أبدًا، كي لا تنهار
حلقة الخلفية. رفع السحابة متزامن (httpx) ويجري داخل ``asyncio.to_thread``.
"""
import json
import os
import shutil
from typing import List, Optional, Tuple

import httpx

TIMEOUT = 120.0
# المجلد الفرعي الافتراضي داخل الحساب السحابي
CLOUD_FOLDER = "HospitalBackups"


class BackupSyncError(Exception):
    """خطأ متوقَّع في الاتصال أو التوثيق — رسالته جاهزة للعرض."""


def default_backup_dir() -> str:
    """مجلد النسخ الافتراضي — مصدر واحد للراوتر وللنسخ المجدولة.

    بجانب main.py في التشغيل العادي، وبجانب الملف التنفيذي في نسخة
    PyInstaller. التوحيد ضروري: كان المسار يُحسب في موضعين بعمقٍ مختلف
    (``app/tasks.py`` ⇐ جذر المشروع، و``app/routers/backup.py`` ⇐ خطأ بمستوى
    داخل ``app/``) فتذهب النسخ اليدوية والمجدولة إلى مجلدَين، ولا تعرض
    الواجهة إلا أحدهما.
    """
    import sys
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "backups")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "backups")


# ---------------------------------------------------------------- أدوات عامة
def _need(config: dict, *keys: str) -> None:
    missing = [k for k in keys if not (config or {}).get(k)]
    if missing:
        raise BackupSyncError("إعدادات ناقصة: " + "، ".join(missing))


def _filename(path: str) -> str:
    return os.path.basename(path)


# ---------------------------------------------------------------- محلي
def _local_dir(config: dict) -> str:
    _need(config, "path")
    path = os.path.expanduser(str(config["path"]))
    os.makedirs(path, exist_ok=True)
    return path


def _local_upload(config: dict, src: str) -> Tuple[bool, str]:
    dest_dir = _local_dir(config)
    dest = os.path.join(dest_dir, _filename(src))
    if os.path.abspath(dest) == os.path.abspath(src):
        return True, "الوجهة هي المجلد الأصلي — لا حاجة للنسخ"
    shutil.copy2(src, dest)
    return True, f"نُسخ إلى {dest_dir}"


def _local_list(config: dict) -> List[str]:
    dest_dir = _local_dir(config)
    return [n for n in sorted(os.listdir(dest_dir), reverse=True)
            if n.endswith(".db")]


def _local_delete(config: dict, name: str) -> Tuple[bool, str]:
    path = os.path.join(_local_dir(config), os.path.basename(name))
    if not os.path.exists(path):
        return True, "غير موجودة (سبق حذفها)"
    os.remove(path)
    return True, f"حُذفت {name}"


# --------------------------------------------------------- Google Drive
def _gdrive_token(config: dict) -> str:
    _need(config, "client_id", "client_secret", "refresh_token")
    try:
        r = httpx.post("https://oauth2.googleapis.com/token", timeout=TIMEOUT, data={
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "refresh_token": config["refresh_token"],
            "grant_type": "refresh_token",
        })
    except httpx.HTTPError as e:
        raise BackupSyncError(f"تعذّر الاتصال بـGoogle: {e}") from e
    if r.status_code != 200:
        raise BackupSyncError(f"رفض Google الترويسة ({r.status_code}): "
                              f"{r.text[:180]}")
    tok = r.json().get("access_token")
    if not tok:
        raise BackupSyncError("لم يُرجع Google وصولًا صالحًا")
    return tok


def _gdrive_upload(config: dict, src: str) -> Tuple[bool, str]:
    token = _gdrive_token(config)
    name = _filename(src)
    meta = {"name": name}
    if config.get("folder_id"):
        meta["parents"] = [config["folder_id"]]
    with open(src, "rb") as fh:
        files = {
            "metadata": (None, json.dumps(meta), "application/json"),
            "file": (name, fh, "application/octet-stream"),
        }
        try:
            r = httpx.post(
                "https://www.googleapis.com/upload/drive/v3/files",
                params={"uploadType": "multipart"},
                headers={"Authorization": "Bearer " + token},
                files=files, timeout=TIMEOUT)
        except httpx.HTTPError as e:
            raise BackupSyncError(f"تعذّر الرفع إلى Google Drive: {e}") from e
    if r.status_code >= 300:
        raise BackupSyncError(f"Google Drive رفض الرفع ({r.status_code}): "
                              f"{r.text[:180]}")
    return True, "رُفع إلى Google Drive"


def _gdrive_list(config: dict) -> List[Tuple[str, str]]:
    """تُرجع (اسم الملف، المعرِّف) مرتبة تنازليًّا."""
    token = _gdrive_token(config)
    q = f"name contains 'hospital' or name contains 'auto' or name contains 'sched'"
    try:
        r = httpx.get("https://www.googleapis.com/drive/v3/files",
                      params={"q": q, "fields": "files(name,id)",
                              "orderBy": "name desc", "pageSize": 100},
                      headers={"Authorization": "Bearer " + token}, timeout=TIMEOUT)
    except httpx.HTTPError as e:
        raise BackupSyncError(f"تعذّر سرد ملفات Google: {e}") from e
    if r.status_code >= 300:
        raise BackupSyncError(f"Google رفض السرد ({r.status_code})")
    return [(f["name"], f["id"]) for f in r.json().get("files", [])]


def _gdrive_delete(config: dict, file_id: str) -> Tuple[bool, str]:
    token = _gdrive_token(config)
    try:
        r = httpx.delete(f"https://www.googleapis.com/drive/v3/files/{file_id}",
                         headers={"Authorization": "Bearer " + token},
                         timeout=TIMEOUT)
    except httpx.HTTPError as e:
        raise BackupSyncError(f"تعذّر الحذف من Google: {e}") from e
    if r.status_code >= 300 and r.status_code != 404:
        raise BackupSyncError(f"Google رفض الحذف ({r.status_code})")
    return True, "حُذفت من Google Drive"


# ------------------------------------------------------------- OneDrive
def _onedrive_token(config: dict) -> str:
    _need(config, "client_id", "refresh_token")
    data = {"client_id": config["client_id"],
            "refresh_token": config["refresh_token"],
            "grant_type": "refresh_token",
            "scope": "https://graph.microsoft.com/Files.ReadWrite offline_access"}
    if config.get("client_secret"):
        data["client_secret"] = config["client_secret"]
    try:
        r = httpx.post(
            "https://login.microsoftonline.com/common/oauth2/v2.0/token",
            data=data, timeout=TIMEOUT)
    except httpx.HTTPError as e:
        raise BackupSyncError(f"تعذّر الاتصال بـMicrosoft: {e}") from e
    if r.status_code != 200:
        raise BackupSyncError(f"رفض Microsoft الترويسة ({r.status_code}): "
                              f"{r.text[:180]}")
    tok = r.json().get("access_token")
    if not tok:
        raise BackupSyncError("لم يُرجع Microsoft وصولًا صالحًا")
    return tok


def _od_path(config: dict) -> str:
    folder = (config.get("folder") or CLOUD_FOLDER).strip("/ ")
    return folder


def _onedrive_upload(config: dict, src: str) -> Tuple[bool, str]:
    token = _onedrive_token(config)
    name = _filename(src)
    url = (f"https://graph.microsoft.com/v1.0/me/drive/root:/"
           f"{_od_path(config)}/{name}:/content")
    try:
        with open(src, "rb") as fh:
            r = httpx.put(url, content=fh.read(),
                          headers={"Authorization": "Bearer " + token},
                          timeout=TIMEOUT)
    except httpx.HTTPError as e:
        raise BackupSyncError(f"تعذّر الرفع إلى OneDrive: {e}") from e
    if r.status_code >= 300:
        raise BackupSyncError(f"OneDrive رفض الرفع ({r.status_code}): "
                              f"{r.text[:180]}")
    return True, "رُفع إلى OneDrive"


def _onedrive_list(config: dict) -> List[Tuple[str, str]]:
    token = _onedrive_token(config)
    url = (f"https://graph.microsoft.com/v1.0/me/drive/root:/"
           f"{_od_path(config)}:/children")
    try:
        r = httpx.get(url, params={"$orderby": "name desc", "$top": "100"},
                      headers={"Authorization": "Bearer " + token}, timeout=TIMEOUT)
    except httpx.HTTPError as e:
        raise BackupSyncError(f"تعذّر سرد ملفات OneDrive: {e}") from e
    if r.status_code >= 300:
        raise BackupSyncError(f"OneDrive رفض السرد ({r.status_code})")
    return [(v["name"], v["id"]) for v in r.json().get("value", [])]


def _onedrive_delete(config: dict, item_id: str) -> Tuple[bool, str]:
    token = _onedrive_token(config)
    try:
        r = httpx.delete(f"https://graph.microsoft.com/v1.0/me/drive/items/{item_id}",
                         headers={"Authorization": "Bearer " + token}, timeout=TIMEOUT)
    except httpx.HTTPError as e:
        raise BackupSyncError(f"تعذّر الحذف من OneDrive: {e}") from e
    if r.status_code >= 300 and r.status_code != 404:
        raise BackupSyncError(f"OneDrive رفض الحذف ({r.status_code})")
    return True, "حُذفت من OneDrive"


# ---------------------------------------------------------------- WebDAV
def _dav_headers(config: dict) -> dict:
    _need(config, "url")
    import base64
    h = {}
    if config.get("username"):
        raw = f"{config['username']}:{config.get('password', '')}".encode()
        h["Authorization"] = "Basic " + base64.b64encode(raw).decode()
    return h


def _dav_base(config: dict) -> str:
    return str(config["url"]).rstrip("/") + "/"


def _webdav_upload(config: dict, src: str) -> Tuple[bool, str]:
    headers = dict(_dav_headers(config), **{"Content-Type": "application/octet-stream"})
    url = _dav_base(config) + _filename(src)
    try:
        with open(src, "rb") as fh:
            r = httpx.request("PUT", url, content=fh.read(),
                              headers=headers, timeout=TIMEOUT)
    except httpx.HTTPError as e:
        raise BackupSyncError(f"تعذّر الرفع عبر WebDAV: {e}") from e
    if r.status_code not in (200, 201, 204):
        raise BackupSyncError(f"WebDAV رفض الرفع ({r.status_code}): {r.text[:180]}")
    return True, "رُفع عبر WebDAV"


def _webdav_list(config: dict) -> List[str]:
    headers = dict(_dav_headers(config), **{"Depth": "1"})
    try:
        r = httpx.request("PROPFIND", _dav_base(config), headers=headers,
                          content=b'<?xml version="1.0"?><d:propfind '
                                  b'xmlns:d="DAV:"><d:prop><d:displayname/>'
                                  b'</d:prop></d:propfind>', timeout=TIMEOUT)
    except httpx.HTTPError as e:
        raise BackupSyncError(f"تعذّر سرد WebDAV: {e}") from e
    if r.status_code not in (200, 207):
        raise BackupSyncError(f"WebDAV رفض السرد ({r.status_code})")
    import re
    names = re.findall(r"<d:displayname>([^<]+)</d:displayname>", r.text)
    return sorted((n for n in names if n.endswith(".db")), reverse=True)


def _webdav_delete(config: dict, name: str) -> Tuple[bool, str]:
    url = _dav_base(config) + os.path.basename(name)
    try:
        r = httpx.request("DELETE", url, headers=_dav_headers(config), timeout=TIMEOUT)
    except httpx.HTTPError as e:
        raise BackupSyncError(f"تعذّر الحذف عبر WebDAV: {e}") from e
    if r.status_code not in (200, 204, 404):
        raise BackupSyncError(f"WebDAV رفض الحذف ({r.status_code})")
    return True, "حُذفت من وجهة WebDAV"


# ------------------------------------------------------------------- HTTP
def _http_upload(config: dict, src: str) -> Tuple[bool, str]:
    _need(config, "url")
    headers = {}
    if config.get("token"):
        headers["Authorization"] = "Bearer " + str(config["token"])
    try:
        with open(src, "rb") as fh:
            r = httpx.post(str(config["url"]), files={"file": (_filename(src), fh)},
                           data={"kind": "database_backup"}, headers=headers,
                           timeout=TIMEOUT)
    except httpx.HTTPError as e:
        raise BackupSyncError(f"تعذّر الرفع إلى الخادم البعيد: {e}") from e
    if r.status_code >= 300:
        raise BackupSyncError(f"الخادم البعيد رفض الرفع ({r.status_code}): "
                              f"{r.text[:180]}")
    return True, "رُفع إلى الخادم البعيد"


# ================================================================ الواجهة
def upload(kind: str, config: dict, src: str) -> Tuple[bool, str]:
    """يرفع نسخة واحدة إلى وجهة — يُرجع (نجاح، رسالة). لا يرمي أبدًا."""
    try:
        # النوع أولًا: رسالة «نوع غير مدعوم» أوضح من «ملف غير موجود»
        if kind not in ("local", "gdrive", "onedrive", "webdav", "http"):
            return False, f"نوع وجهة غير مدعوم: {kind}"
        if not os.path.isfile(src):
            return False, f"الملف المصدري غير موجود: {src}"
        if kind == "local":
            return _local_upload(config, src)
        if kind == "gdrive":
            return _gdrive_upload(config, src)
        if kind == "onedrive":
            return _onedrive_upload(config, src)
        if kind == "webdav":
            return _webdav_upload(config, src)
        if kind == "http":
            return _http_upload(config, src)
        return False, f"نوع وجهة غير مدعوم: {kind}"   # لا يبلغ: فُحص أعلاه
    except BackupSyncError as e:
        return False, str(e)
    except OSError as e:
        return False, f"خطأ ملفي: {e}"
    except Exception as e:  # noqa: BLE001 — حلقة الخلفية لا تنهار
        return False, f"خطأ غير متوقع: {type(e).__name__}: {e}"


def test_connection(kind: str, config: dict) -> Tuple[bool, str]:
    """يفحص الاتصال بالوجهة دون رفع نسخة (محاولة صغيرة آمنة)."""
    try:
        if kind == "local":
            d = _local_dir(config)
            probe = os.path.join(d, ".connection_test")
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write("ok")
            os.remove(probe)
            return True, f"المجلد صالح: {d}"
        if kind == "gdrive":
            _gdrive_token(config)
            return True, "التوثيق ساري — Google Drive جاهز"
        if kind == "onedrive":
            _onedrive_token(config)
            return True, "التوثيق ساري — OneDrive جاهز"
        if kind == "webdav":
            _webdav_list(config)
            return True, "الاتصال سار — WebDAV يستجيب"
        if kind == "http":
            _need(config, "url")
            return True, "العنوان مضبوط (يُفحص فعليًّا عند أول رفع)"
        return False, f"نوع وجهة غير مدعوم: {kind}"
    except BackupSyncError as e:
        return False, str(e)
    except Exception as e:  # noqa: BLE001
        return False, f"خطأ غير متوقع: {type(e).__name__}: {e}"


def prune_remote(kind: str, config: dict, keep: Optional[int]) -> Tuple[bool, str]:
    """يُبقي آخر ``keep`` نسخ على الوجهة ويحذف ما سواها. keep بلا معنى ⇒ لا شيء."""
    if not keep or keep < 1:
        return True, "لا تقليم مطلوب"
    try:
        if kind == "local":
            names = _local_list(config)
            removed = [n for n in names[keep:] if n.endswith(".db")]
            for n in removed:
                _local_delete(config, n)
            return True, (f"حُذف {len(removed)} زائدًا" if removed
                          else "لا شيء زائد")
        if kind in ("gdrive", "onedrive"):
            fn = (_gdrive_list if kind == "gdrive" else _onedrive_list)
            entries = fn(config)
            removed = entries[keep:]
            deleter = (_gdrive_delete if kind == "gdrive" else _onedrive_delete)
            for _name, fid in removed:
                deleter(config, fid)
            return True, (f"حُذف {len(removed)} زائدًا" if removed
                          else "لا شيء زائد")
        if kind == "webdav":
            names = _webdav_list(config)
            removed = names[keep:]
            for n in removed:
                _webdav_delete(config, n)
            return True, (f"حُذف {len(removed)} زائدًا" if removed
                          else "لا شيء زائد")
        return True, "نوع لا يدعم التقليم (يبقى على بقية الوجهات)"
    except BackupSyncError as e:
        return False, str(e)
    except Exception as e:  # noqa: BLE001
        return False, f"خطأ غير متوقع: {type(e).__name__}: {e}"


# ---------------------------------------------------------- الدفع من الخادم
def push_to_destinations(db, filepath: str) -> List[dict]:
    """يرفع نسخة واحدة إلى كل وجهة مفعّلة ويبقى آخر N على كلٍّ منها.

    تُستدعى من الراوتر ومن حلقة الجدولة على حدٍّ سواء. الفشل في وجهة لا يمنع
    بقيتها: كل وجهة تحفظ ناتجها في صفّها (last_error / last_sync_at) فتُقرأ
    من الواجهة دون مقاطعة، والدالة تُرجع تقريرًا لكل وجهة.
    """
    from datetime import datetime
    from app.models import BackupDestination

    report = []
    for dest in db.query(BackupDestination).filter(
            BackupDestination.enabled.is_(True)).all():
        cfg = dest.config or {}
        ok, msg = upload(dest.kind, cfg, filepath)
        if ok:
            dest.last_sync_at = datetime.now()
            dest.last_file = os.path.basename(filepath)
            dest.last_error = None
            if dest.keep and dest.keep > 0:
                _, pm = prune_remote(dest.kind, cfg, dest.keep)
                msg = f"{msg} · {pm}"
        else:
            dest.last_error = msg
        report.append({"id": dest.id, "name": dest.name, "kind": dest.kind,
                       "ok": ok, "message": msg})
    db.commit()
    return report
