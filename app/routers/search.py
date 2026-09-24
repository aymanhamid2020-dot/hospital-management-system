"""البحث العام السريع (Ctrl+K): مرضى + أدوية + فواتير + مواعيد + وصفات.

نقطة واحدة تغذي لوحة البحث في الواجهة، بنفس قواعد `/prescriptions`
للأدوار (الطبيب يرى وصفات مرضاه فقط).
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import get_current_user, get_user_role
from app.database import get_db
from app.models import (
    Appointment,
    Doctor,
    Invoice,
    Medication,
    Patient,
    Prescription,
    User,
)
from app.routers.prescriptions import _linked_doctor

router = APIRouter(prefix="/search", tags=["البحث"])

_RX_LABELS = {
    "PENDING": "معلّقة",
    "PARTIAL": "مصروفة جزئيًا",
    "DISPENSED": "مصروفة",
    "CANCELLED": "ملغاة",
}


def _hit(kind: str, icon: str, label: str, id_: int,
         title: str, subtitle: str, view: str) -> dict:
    """نتيجة واحدة جاهزة للعرض والقفز (view = اسم شاشة الواجهة)."""
    return {
        "type": kind, "icon": icon, "type_label": label, "id": id_,
        "title": title, "subtitle": subtitle, "view": view,
    }


def _names(db: Session, ids) -> dict:
    """خريطة معرفات المرضى ← الأسماء (استعلام واحد)."""
    ids = {i for i in ids if i is not None}
    if not ids:
        return {}
    return {p.id: p.full_name
            for p in db.query(Patient).filter(Patient.id.in_(ids)).all()}


@router.get("/", summary="بحث عام سريع في النظام")
async def global_search(
    q: str = Query("", description="نص البحث (حرف واحد على الأقل)"),
    limit: int = Query(5, ge=1, le=20, description="أقصى نتائج لكل نوع (1–20)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """يعيد حتى `limit` نتيجة لكل نوع: مرضى، أدوية، فواتير، مواعيد، وصفات.

    كل نتيجة تحمل `view` اسم الشاشة التي تقفز إليها الواجهة، و`type`
    نوع الكيان و`type_label` اسمه بالعربية للعرض المباشر.
    """
    term = (q or "").strip()
    if not term:
        raise HTTPException(
            status_code=400,
            detail="اكتب نص البحث (حرف واحد على الأقل)",
        )
    pat = f"%{term}%"
    # رقم بحث يُطابَق مع معرفات الجداول (يقتصر على طول معرف معقول)
    num = int(term) if term.isdigit() and len(term) <= 9 else None
    results: List[dict] = []

    # 1) المرضى: الاسم/الهاتف/الهوية/رقم الملف
    p_cond = [Patient.full_name.ilike(pat),
              Patient.phone.ilike(pat),
              Patient.national_id.ilike(pat)]
    if num is not None:
        p_cond.append(Patient.id == num)
    for p in (db.query(Patient).filter(or_(*p_cond)).limit(limit).all()):
        parts = [f"هاتف {p.phone}"] if p.phone else []
        if p.national_id:
            parts.append(f"هوية {p.national_id}")
        results.append(_hit("patient", "🧑‍🤝‍🧑", "مريض", p.id,
                            p.full_name, " · ".join(parts), "patients"))

    # 2) الأدوية: الاسم/الرمز/رقم السجل
    m_cond = [Medication.name.ilike(pat), Medication.code.ilike(pat)]
    if num is not None:
        m_cond.append(Medication.id == num)
    for m in (db.query(Medication).filter(or_(*m_cond)).limit(limit).all()):
        results.append(_hit(
            "medication", "💊", "دواء", m.id, m.name,
            f"رمز {m.code} · {m.quantity} {m.unit} · {m.price:.2f} ر.س",
            "inventory"))

    # 3) الفواتير: الوصف/رقم الفاتورة/اسم المريض
    inv_cond = [Invoice.description.ilike(pat)]
    name_pids = [r[0] for r in
                 db.query(Patient.id).filter(Patient.full_name.ilike(pat))
                 .limit(200).all()]
    if name_pids:
        inv_cond.append(Invoice.patient_id.in_(name_pids))
    if num is not None:
        inv_cond.append(Invoice.id == num)
    invoices = db.query(Invoice).filter(or_(*inv_cond)).limit(limit).all()
    ipat = _names(db, [i.patient_id for i in invoices])
    for inv in invoices:
        desc = f" · {inv.description}" if inv.description else ""
        results.append(_hit(
            "invoice", "💳", "فاتورة", inv.id, f"فاتورة #{inv.id}",
            f"{ipat.get(inv.patient_id, '—')} · {inv.amount:.2f} ر.س{desc}",
            "invoices"))

    # 4) المواعيد: اسم المريض/سبب الزيارة/رقم الموعد
    appt_cond = [Patient.full_name.ilike(pat),
                 Appointment.reason.ilike(pat)]
    if num is not None:
        appt_cond.append(Appointment.id == num)
    appts = (db.query(Appointment)
             .join(Patient, Appointment.patient_id == Patient.id)
             .filter(or_(*appt_cond)).limit(limit).all())
    apat = _names(db, [a.patient_id for a in appts])
    doc_ids = {a.doctor_id for a in appts if a.doctor_id}
    dnames = ({d.id: d.full_name for d in
               db.query(Doctor).filter(Doctor.id.in_(doc_ids)).all()}
              if doc_ids else {})
    for a in appts:
        when = (a.appointment_date.strftime("%Y-%m-%d %H:%M")
                if hasattr(a.appointment_date, "strftime")
                else str(a.appointment_date or ""))
        results.append(_hit(
            "appointment", "📅", "موعد", a.id,
            f"موعد #{a.id} — {apat.get(a.patient_id, '—')}",
            f"{when} · {dnames.get(a.doctor_id, 'بدون طبيب')}",
            "appointments"))

    # 5) الوصفات: اسم المريض/الملاحظات/رقم الوصفة (الطبيب: مرضاه فقط)
    rx_cond = [Patient.full_name.ilike(pat),
               Prescription.notes.ilike(pat)]
    if num is not None:
        rx_cond.append(Prescription.id == num)
    rx_q = (db.query(Prescription)
            .join(Patient, Prescription.patient_id == Patient.id)
            .filter(or_(*rx_cond)))
    rxs: List[Prescription] = []
    if get_user_role(current_user) != "doctor":
        rxs = rx_q.limit(limit).all()
    else:
        linked = _linked_doctor(db, current_user)
        if linked is not None:
            rxs = (rx_q.filter(Prescription.doctor_id == linked.id)
                   .limit(limit).all())
    rpat = _names(db, [r.patient_id for r in rxs])
    for rx in rxs:
        date = rx.created_at.strftime("%Y-%m-%d") if rx.created_at else ""
        results.append(_hit(
            "prescription", "📋", "وصفة", rx.id,
            f"وصفة #{rx.id} — {rpat.get(rx.patient_id, '—')}",
            f"{_RX_LABELS.get(rx.status, rx.status)} · {date}",
            "pharmacy"))

    return {"query": term, "results": results}
