# صورة نظام إدارة المستشفيات والعيادات
FROM python:3.12-slim

# متطلبات بناء Pillow/حزم عربية
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# الاعتماديات أولًا (تخزين مؤقت طبقي)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ المشروع
COPY . .

# إنشاء المجلدات التي يحتاجها التشغيل
RUN mkdir -p uploads backups outbox static

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
