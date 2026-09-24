"""نظام المستشفى على سطح المكتب: خادم محلي + فتح المتصفح تلقائيًا.

البناء (ويندوز):
    build_desktop.bat            →  dist\\HospitalMS.exe
التشغيل:
    dist\\HospitalMS.exe          →  يفتح http://127.0.0.1:8765/ui/
    HMS_DESKTOP_PORT=9000 dist\\HospitalMS.exe   (منفذ مخصّص)

النسخة المجمّعة تضع قاعدة البيانات hospital.db والنسخ الاحتياطية بجانب
الملف التنفيذي (مجلد التشغيل)، وتعمل دون تثبيت أي شيء.
"""
import os
import sys
import threading
import time
import webbrowser

PORT = int(os.getenv("HMS_DESKTOP_PORT", "8765"))


def _prepare_env():
    """ضبط البيئة قبل استيراد التطبيق (خاصة في وضع الـ frozen)."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
        os.chdir(base)
        os.environ.setdefault(
            "DATABASE_URL", "sqlite:///" + os.path.join(base, "hospital.db"))
        os.environ.setdefault("SECRET_KEY", "desktop-local-only-change-me")
    os.environ.setdefault("DEBUG", "false")
    os.environ.setdefault("CORS_ORIGINS", "*")


def _open_browser():
    time.sleep(2.5)
    webbrowser.open(f"http://127.0.0.1:{PORT}/ui/")


def main():
    _prepare_env()
    threading.Thread(target=_open_browser, daemon=True).start()
    # استيراد static حتى يجمّعه PyInstaller (يجب أن يكون بعد تجهيز البيئة)
    import main as app_main
    import uvicorn

    print(f"🏥 نظام إدارة المستشفيات — http://127.0.0.1:{PORT}/ui/")
    uvicorn.run(app_main.app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
