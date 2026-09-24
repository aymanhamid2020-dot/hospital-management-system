from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import get_current_user, get_user_role, require_admin
from app.database import get_db
from app.models import (
    LabOrder, LabStatus, Notification, Patient, Doctor, User,
)
from app.schemas import LabOrderCreate, LabOrderInDB, LabOrderUpdate

router = APIRouter(prefix="/lab-orders", tags=["Lab & Radiology"])


def _doctor_can_access(db: Session, current_user: User, order: LabOrder) -> bool:
    """طبيب مرتبط بسجل طبيب: يصل فقط لطلباته — باقي الأدوار (مدير/استقبال) غير مقيّدة."""
    if get_user_role(current_user) != "doctor":
        return True
    linked = db.query(Doctor).filter(Doctor.email == current_user.email).first()
    return linked is not None and order.doctor_id == linked.id


@router.get("/", response_model=List[LabOrderInDB], summary="عرض طلبات المختبر والأشعة")
async def list_lab_orders(
    patient_id: Optional[int] = Query(None, description="فلترة حسب المريض"),
    doctor_id: Optional[int] = Query(None, description="فلترة حسب الطبيب"),
    status_filter: Optional[str] = Query(None, alias="status", description="فلترة حسب الحالة"),
    test_type: Optional[str] = Query(None, description="lab / radiology"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """جلب طلبات التحاليل — الطبيب يرى طلبات مرضاه فقط"""
    q = db.query(LabOrder)

    if get_user_role(current_user) == "doctor":
        linked = db.query(Doctor).filter(Doctor.email == current_user.email).first()
        if linked is None:
            return []
        q = q.filter(LabOrder.doctor_id == linked.id)

    if patient_id is not None:
        q = q.filter(LabOrder.patient_id == patient_id)
    if doctor_id is not None:
        q = q.filter(LabOrder.doctor_id == doctor_id)
    if status_filter:
        q = q.filter(LabOrder.status == status_filter)
    if test_type:
        q = q.filter(LabOrder.test_type == test_type)
    return q.order_by(LabOrder.ordered_at.desc()).all()


@router.get("/{order_id}", response_model=LabOrderInDB, summary="عرض طلب معين")
async def get_lab_order(order_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    order = db.query(LabOrder).filter(LabOrder.id == order_id).first()
    if not order or not _doctor_can_access(db, current_user, order):
        raise HTTPException(status_code=404, detail="لا يوجد طلب بالمعرف المحدد")
    return order


@router.get("/{order_id}/pdf", summary="طباعة ورقة نتيجة الطلب PDF")
async def print_lab_order(
    order_id: int,
    lang: str = Query("ar", description="ar | en"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """ورقة نتيجة المختبر/الأشعة — صلاحية العرض مطابقة لعرض الطلب (404)."""
    if lang not in ("ar", "en"):
        raise HTTPException(status_code=400, detail="lang يجب أن يكون ar أو en")
    order = db.query(LabOrder).filter(LabOrder.id == order_id).first()
    if not order or not _doctor_can_access(db, current_user, order):
        raise HTTPException(status_code=404, detail="لا يوجد طلب بالمعرف المحدد")
    from fastapi.responses import Response

    from app.pdf_utils import lab_result_pdf

    filename = f"lab_result_{order.id}{'_en' if lang == 'en' else ''}.pdf"
    return Response(
        content=lab_result_pdf(order, lang=lang),
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="{filename}"'},
    )


@router.post("/", response_model=LabOrderInDB, summary="طلب تحليل/أشعة جديد")
async def create_lab_order(
    order: LabOrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """إنشاء طلب مختبر أو أشعة لمريض — الطبيب يُنسب له تلقائيًا ولا ينشئ لغيره"""
    patient = db.query(Patient).filter(Patient.id == order.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="لا يوجد مريض بالمعرف المحدد")
    if order.doctor_id is not None:
        doctor = db.query(Doctor).filter(Doctor.id == order.doctor_id).first()
        if not doctor:
            raise HTTPException(status_code=404, detail="لا يوجد طبيب بالمعرف المحدد")

    data = order.model_dump()
    if get_user_role(current_user) == "doctor":
        linked = db.query(Doctor).filter(Doctor.email == current_user.email).first()
        if linked is None:
            raise HTTPException(status_code=403, detail="حسابك غير مرتبط بسجل طبيب")
        if data.get("doctor_id") is not None and data["doctor_id"] != linked.id:
            raise HTTPException(status_code=403, detail="يمكنك إنشاء طلباتك فقط")
        data["doctor_id"] = linked.id

    db_order = LabOrder(**data)
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    return db_order


@router.put("/{order_id}", response_model=LabOrderInDB, summary="تحديث طلب (نتيجة/حالة)")
async def update_lab_order(
    order_id: int,
    update: LabOrderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """إدخال النتيجة أو تغيير حالة الطلب — عند جاهزية النتيجة يُنشأ إشعار"""
    order = db.query(LabOrder).filter(LabOrder.id == order_id).first()
    if not order or not _doctor_can_access(db, current_user, order):
        raise HTTPException(status_code=404, detail="لا يوجد طلب بالمعرف المحدد")

    data = update.model_dump(exclude_unset=True)

    # النتيجة مطلوبة لحين وصول الطلب إلى "جاهزة"
    new_status = data.get("status")
    result_text = data.get("result", order.result)
    if new_status in (LabStatus.READY, LabStatus.REVIEWED) and not (result_text or "").strip():
        raise HTTPException(status_code=400, detail="أدخل نتيجة الطلب قبل جعله جاهزًا")

    became_ready = (
        new_status == LabStatus.READY and order.status != LabStatus.READY
    )

    for field, value in data.items():
        setattr(order, field, value)

    if became_ready:
        order.result_at = datetime.now()
        db.add(Notification(
            type="lab_result",
            title="نتيجة تحليل جاهزة",
            message=f"نتيجة طلب «{order.test_name}» للمريض {order.patient.full_name if order.patient else '-'} أصبحت جاهزة",
            patient_id=order.patient_id,
        ))

    db.commit()
    db.refresh(order)

    # إشعار فوري اختياري (تلغرام/ويبهوك) عند جاهزية النتيجة — لا يُصعّد أبدًا
    if became_ready:
        from app.notifier import notify
        notify("lab_result",
               f"نتيجة «{order.test_name}» للمريض "
               f"{order.patient.full_name if order.patient else '-'} أصبحت جاهزة")
    return order


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT, summary="حذف طلب")
async def delete_lab_order(
    order_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """حذف طلب (للمدير فقط)"""
    order = db.query(LabOrder).filter(LabOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="لا يوجد طلب بالمعرف المحدد")
    db.delete(order)
    db.commit()
    return None
