"""إشعارات فورية اختيارية — Telegram Bot و/أو Webhook عام.

تُستدعى من نقاط الحدث (جاهزية نتيجة، مخزون منخفض، تذكير بالمواعيد) ولا
ترفع استثناء أبدًا: أي إخفاق يُسجَّل ويمرّر الطلب الأصلي كما هو.

الضبط عبر البيئة (تُمرَّر تلقائيًا من docker-compose):
    TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID   → إرسال عبر تلغرام
    NOTIFY_WEBHOOK_URL                      → POST JSON عام
        {"kind", "text", "service", "time"}
"""
import json
import logging
import os
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger("hms.notify")


def _http_post_json(url: str, payload: dict, timeout: float = 5.0) -> None:
    """POST JSON عبر مكتبة urllib المدمجة (بلا تبعيات إضافية)."""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout):
        pass


def notify(kind: str, text: str) -> bool:
    """إرسال إشعار فوري إن ضُبطت قناة — True إذا أُرسل بنجاح لأي قناة.

    إخفاق الشبكة أو الإعداد الناقص لا يُصعّد أبدًا (الإشعار جانبي اختياري).
    """
    sent = False
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    hook = os.getenv("NOTIFY_WEBHOOK_URL", "")

    if token and chat_id:
        try:
            _http_post_json(
                f"https://api.telegram.org/bot{token}/sendMessage",
                {"chat_id": chat_id, "text": f"[نظام المستشفى — {kind}]\n{text}"},
            )
            sent = True
        except Exception as exc:
            logger.warning("telegram notify failed: %s", exc)

    if hook:
        try:
            _http_post_json(hook, {
                "kind": kind,
                "text": text,
                "service": "hospital-management-system",
                "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            sent = True
        except Exception as exc:
            logger.warning("webhook notify failed: %s", exc)

    return sent
