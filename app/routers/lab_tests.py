from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin
from app.database import get_db
from app.models import LabTest, TestType, User
from app.schemas import LabTestCreate, LabTestInDB, LabTestUpdate

router = APIRouter(prefix="/lab-tests", tags=["Lab & Radiology"])


def _check_range(ref_min: Optional[float], ref_max: Optional[float]) -> None:
    """النطاق الطبيعي: إن وُجد الحدان فيجب أن يكون الأدنى ≤ الأعلى."""
    if ref_min is not None and ref_max is not None and ref_min > ref_max:
        raise HTTPException(status_code=400,
                            detail="النطاق الطبيعي: الحد الأدنى يجب أن يكون ≤ الأعلى")


def _normalize_category(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if value not in ("lab", "radiology"):
        raise HTTPException(status_code=400, detail="category يجب أن يكون lab أو radiology")
    return value


@router.get("/", response_model=List[LabTestInDB], summary="دليل الفحوصات")
async def list_lab_tests(
    category: Optional[str] = Query(None, description="lab / radiology"),
    active_only: bool = Query(False, description="المفعّلة فقط في نموذج الطلب"),
    search: Optional[str] = Query(None, description="بحث بالرمز أو الاسم"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """قائمة كتالوج الفحوصات (الأسعار وشروط الصيام وأنواع الأنابيب والنطاقات)"""
    q = db.query(LabTest)
    cat = _normalize_category(category)
    if cat:
        q = q.filter(LabTest.category == TestType(cat))
    if active_only:
        q = q.filter(LabTest.active.is_(True))
    if search and search.strip():
        like = f"%{search.strip()}%"
        q = q.filter((LabTest.code.ilike(like)) | (LabTest.name.ilike(like)))
    return q.order_by(LabTest.category, LabTest.code).all()


@router.post("/", response_model=LabTestInDB, status_code=status.HTTP_201_CREATED,
             summary="إضافة فحص إلى الدليل")
async def create_lab_test(
    payload: LabTestCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """تعريف فحص جديد بسعره وشرط الصيام ونوع الأنبوب والنطاق الطبيعي (مدير فقط)"""
    _check_range(payload.ref_min, payload.ref_max)
    code = payload.code.strip()
    if db.query(LabTest).filter(LabTest.code == code).first():
        raise HTTPException(status_code=409, detail="رمز الفحص مستخدم مسبقًا")
    row = LabTest(**payload.model_dump())
    row.code = code
    row.name = payload.name.strip()
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/{test_id}", response_model=LabTestInDB, summary="تحديث فحص في الدليل")
async def update_lab_test(
    test_id: int,
    payload: LabTestUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """تحديث جزئي — الحقول غير المرسلة تبقى كما هي (مدير فقط)"""
    row = db.query(LabTest).filter(LabTest.id == test_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="لا يوجد فحص بالمعرف المحدد")

    data = payload.model_dump(exclude_unset=True)
    new_min = data.get("ref_min", row.ref_min)
    new_max = data.get("ref_max", row.ref_max)
    _check_range(new_min, new_max)
    if "code" in data:
        code = (data["code"] or "").strip()
        if not code:
            raise HTTPException(status_code=400, detail="رمز الفحص مطلوب")
        clash = (db.query(LabTest)
                 .filter(LabTest.code == code, LabTest.id != test_id).first())
        if clash:
            raise HTTPException(status_code=409, detail="رمز الفحص مستخدم مسبقًا")
        data["code"] = code
    if "name" in data:
        data["name"] = (data["name"] or "").strip()

    for field, value in data.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{test_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="حذف فحص من الدليل")
async def delete_lab_test(
    test_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """حذف فحص لم يُطلب بعد — الطلبات المرتبطة تبقى سليمة (FK SET NULL) (مدير فقط)"""
    row = db.query(LabTest).filter(LabTest.id == test_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="لا يوجد فحص بالمعرف المحدد")
    db.delete(row)
    db.commit()
    return None
