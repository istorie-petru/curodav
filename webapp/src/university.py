"""The University module: registers itself with the module framework (src/modules.py).

4.7.0 ships only the scaffolding: the module is off unless CC_MODULES lists `university`, its Settings page is empty, and its
tables, JSON format (`study_format.py`) and pasted-list parser (`study_lists.py`) exist without any screen using them. The
semester, timetable, syllabus, exam and reading screens arrive in 4.8.0 (features/university-module.md).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from . import modules
from .deps import get_db, templates

MODULE = modules.register(modules.Module("university", "University", "/settings/university", icon="graduation-cap"))

router = APIRouter(prefix="/settings/university", tags=["university"])


@router.get("")
def university_settings(request: Request, conn=Depends(get_db)):
    if not modules.is_enabled(MODULE.key):
        raise HTTPException(404, "Not found")
    return templates.TemplateResponse("settings_university.html", {"request": request})
