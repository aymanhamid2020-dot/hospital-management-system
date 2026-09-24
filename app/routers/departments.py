from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models import Department, User
from app.schemas import DepartmentCreate, DepartmentUpdate, DepartmentInDB
from app.auth import get_current_user, require_admin

router = APIRouter(prefix="/departments", tags=["Departments"])


@router.get("/", response_model=List[DepartmentInDB], summary="عرض قائمة الأقسام")
async def list_departments(db = Depends(get_db), _ = Depends(get_current_user)):
    """جلب كل الأقسام مع أسرّتها"""
    return db.query(Department).all()


@router.get("/{dept_id}", response_model=DepartmentInDB, summary="عرض قسم معين")
async def get_department(dept_id: int, db = Depends(get_db), _ = Depends(get_current_user)):
    dept = db.query(Department).filter(Department.id == dept_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="لا يوجد قسم بالمعرف المحدد")
    return dept


@router.post("/", response_model=DepartmentInDB, summary="إضافة قسم جديد")
async def create_department(
    dept: DepartmentCreate,
    db = Depends(get_db),
    _: User = Depends(require_admin),
):
    """إضافة قسم (للمدير فقط)"""
    if db.query(Department).filter(Department.name == dept.name).first():
        raise HTTPException(status_code=400, detail="اسم القسم موجود بالفعل")
    db_dept = Department(**dept.model_dump())
    db.add(db_dept)
    db.commit()
    db.refresh(db_dept)
    return db_dept


@router.put("/{dept_id}", response_model=DepartmentInDB, summary="تحديث قسم")
async def update_department(
    dept_id: int,
    dept: DepartmentUpdate,
    db = Depends(get_db),
    _: User = Depends(require_admin),
):
    db_dept = db.query(Department).filter(Department.id == dept_id).first()
    if not db_dept:
        raise HTTPException(status_code=404, detail="لا يوجد قسم بالمعرف المحدد")
    for field, value in dept.model_dump(exclude_unset=True).items():
        setattr(db_dept, field, value)
    db.commit()
    db.refresh(db_dept)
    return db_dept


@router.delete("/{dept_id}", status_code=status.HTTP_204_NO_CONTENT, summary="حذف قسم")
async def delete_department(
    dept_id: int,
    db = Depends(get_db),
    _: User = Depends(require_admin),
):
    db_dept = db.query(Department).filter(Department.id == dept_id).first()
    if not db_dept:
        raise HTTPException(status_code=404, detail="لا يوجد قسم بالمعرف المحدد")
    db.delete(db_dept)
    db.commit()
    return None
