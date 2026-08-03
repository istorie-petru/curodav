#!/usr/bin/env python3
"""Replaces ALL of this app's current data with a university-themed demo
dataset that exercises every feature: multi-calendar + multi-task-list +
multi-addressbook, tasks (subtasks, checklists, kanban statuses,
priorities, a recurring task), a class Schedule (odd/even parity, holiday
exceptions, mirrored calendar events, conflict/credits detection), Tags
(with groups), Projects (with groups + archiving), Habits (streaks +
partial-quantity heatmap), custom Databases (a formula + weighted-average
grade tracker, and a simple checklist-style reading list), and every
Dashboard widget type.

WHAT THIS TOUCHES
------------------
Radicale is this app's source of truth for events/tasks/contacts (see
src/db.py's module docstring) -- this script pushes real VEVENT/VTODO/
vCard objects through the same CalDavBridge the app itself uses
(src/caldav_bridge.py), so the result is indistinguishable from data
created by hand through the UI. Everything else (projects, tags, habits,
custom databases, schedule, dashboard widgets) is local-only and is
written straight to the SQLite cache (src/db.py) -- there's no CalDAV
equivalent for those (see db.py's docstring for why).

This script starts and stops its OWN throwaway dev Radicale instance,
using the exact same config/storage/htpasswd run.sh does. Because of that:

  >>> Stop the app (Ctrl+C on run.sh) before running this. <<<

Running both at once double-binds 127.0.0.1:5232 and one of them will fail.

SAFETY
------
Nothing is deleted outright. The existing Radicale collections folder and
SQLite cache file are each moved aside with a timestamp suffix
(.dev/radicale/collections.bak-<ts>, cache.sqlite.bak-<ts>) before fresh
ones are created, so the previous state is fully recoverable by moving
them back and deleting what this script created.

USAGE
-----
    cd webapp
    uv run python scripts/seed_university_data.py
"""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

WEBAPP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WEBAPP_DIR))

# Match run.sh's defaults exactly, but don't clobber anything the caller
# already exported (e.g. pointing this at a non-default Radicale).
os.environ.setdefault("CC_RADICALE_URL", "http://127.0.0.1:5232/devuser/")
os.environ.setdefault("CC_RADICALE_USER", "devuser")
os.environ.setdefault("CC_RADICALE_PASSWORD", "devpass")
os.environ.setdefault("CC_CALENDAR_COLLECTION", "calendar")
os.environ.setdefault("CC_TASKS_COLLECTION", "tasks")
os.environ.setdefault("CC_CONTACTS_COLLECTION", "contacts")

from src import db, sync  # noqa: E402
from src.caldav_bridge import CalDavBridge  # noqa: E402
from src.config import load_settings  # noqa: E402
from src.schedule import class_to_event_row  # noqa: E402

RNG = random.Random(20260801)  # deterministic habit history

TODAY = date.today()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    return str(uuid.uuid4())


def iso(d: date) -> str:
    return d.isoformat()


# --------------------------------------------------------------------- #
# Step 0: move existing state aside, start a fresh throwaway Radicale
# --------------------------------------------------------------------- #


def backup_and_reset_radicale_storage() -> Path:
    collections_dir = WEBAPP_DIR / ".dev" / "radicale" / "collections"
    if collections_dir.exists():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = collections_dir.with_name(f"collections.bak-{ts}")
        shutil.move(str(collections_dir), str(backup))
        print(f"  moved old Radicale storage -> {backup.relative_to(WEBAPP_DIR)}")
    collections_dir.mkdir(parents=True, exist_ok=True)
    return collections_dir


def backup_sqlite_cache(db_path: Path) -> None:
    if db_path.exists():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = db_path.with_name(f"{db_path.name}.bak-{ts}")
        shutil.move(str(db_path), str(backup))
        print(f"  moved old sqlite cache -> {backup}")
    for suffix in ("-wal", "-shm"):
        stray = db_path.with_name(db_path.name + suffix)
        if stray.exists():
            stray.unlink()


def start_radicale(collections_dir: Path) -> subprocess.Popen:
    cmd = [
        sys.executable,
        "-m",
        "radicale",
        "--config",
        str(WEBAPP_DIR / ".dev" / "radicale" / "config"),
        f"--storage-filesystem_folder={collections_dir}",
        f"--auth-htpasswd_filename={WEBAPP_DIR / '.dev' / 'radicale' / 'users'}",
    ]
    print("  starting throwaway Radicale ...")
    proc = subprocess.Popen(cmd, cwd=WEBAPP_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2.5)
    if proc.poll() is not None:
        raise RuntimeError(
            "Radicale exited immediately -- is another instance (e.g. run.sh) already "
            "bound to 127.0.0.1:5232? Stop it and re-run this script."
        )
    return proc


# --------------------------------------------------------------------- #
# Content
# --------------------------------------------------------------------- #

SEMESTER_START = date(2026, 8, 24)
SEMESTER_END = date(2026, 12, 11)


def build(conn, bridge: CalDavBridge) -> None:
    db.ensure_default_calendar(conn)
    db.ensure_default_task_list(conn)
    db.ensure_default_addressbook(conn)

    # ---------------------------------------------------------------- #
    # Tag groups + tags
    # ---------------------------------------------------------------- #
    print("  tags ...")
    tag_group_subjects = uid()
    tag_group_priority = uid()
    db.upsert_tag_group(conn, {"uid": tag_group_subjects, "name": "Subjects", "created_at": now_iso()})
    db.upsert_tag_group(conn, {"uid": tag_group_priority, "name": "Priority", "created_at": now_iso()})

    tags = {
        "CS": ("blue", tag_group_subjects),
        "Math": ("green", tag_group_subjects),
        "Physics": ("purple", tag_group_subjects),
        "Writing": ("orange", tag_group_subjects),
        "Capstone": ("red", tag_group_subjects),
        "Urgent": ("red", tag_group_priority),
        "Important": ("yellow", tag_group_priority),
        "Low Priority": ("gray", tag_group_priority),
        "Reading": ("teal", None),
        "Lab": ("indigo", None),
        "Group Project": ("pink", None),
        "Schedule": ("gray", None),
    }
    tag_uids: dict[str, str] = {}
    for name, (color, group_uid) in tags.items():
        tag_uids[name] = uid()
        db.upsert_tag(conn, {"uid": tag_uids[name], "name": name, "color": color, "group_uid": group_uid, "created_at": now_iso()})

    # ---------------------------------------------------------------- #
    # Project groups + projects
    # ---------------------------------------------------------------- #
    print("  projects ...")
    pg_courses = uid()
    pg_campus = uid()
    db.upsert_project_group(conn, {"uid": pg_courses, "name": "Courses", "created_at": now_iso()})
    db.upsert_project_group(conn, {"uid": pg_campus, "name": "Campus Life", "created_at": now_iso()})

    projects = {
        "cs301": dict(name="CS 301 – Algorithms & Data Structures", color="blue", icon="\U0001F4BB", group_uid=pg_courses,
                      description="Core CS course: asymptotic analysis, trees/graphs, sorting, and dynamic programming."),
        "math241": dict(name="MATH 241 – Linear Algebra", color="green", icon="➗", group_uid=pg_courses,
                         description="Vector spaces, matrices, eigenvalues -- required for the CS major."),
        "phys210": dict(name="PHYS 210 – Modern Physics", color="purple", icon="⚛️", group_uid=pg_courses,
                         description="Relativity and intro quantum mechanics, with a weekly lab."),
        "eng150": dict(name="ENG 150 – Academic Writing", color="orange", icon="✍️", group_uid=pg_courses,
                        description="General-ed writing requirement."),
        "capstone": dict(name="Senior Capstone Project", color="red", icon="\U0001F393", group_uid=pg_courses,
                          description="Two-semester capstone: build, document, and present an original project."),
        "studentgov": dict(name="Student Government – Treasurer", color="teal", icon="\U0001F3DB️", group_uid=pg_campus,
                            description="Budget management and event funding for the student senate."),
    }
    project_uids: dict[str, str] = {}
    for key, p in projects.items():
        project_uids[key] = uid()
        db.upsert_project(conn, {
            "uid": project_uids[key], "name": p["name"], "description": p["description"],
            "color": p["color"], "icon": p["icon"], "cover_image_b64": None, "cover_image_type": None,
            "group_uid": p["group_uid"], "archived_at": None, "created_at": now_iso(), "updated_at": now_iso(),
        })

    # An archived project, to showcase archive/unarchive.
    old_project_uid = uid()
    db.upsert_project(conn, {
        "uid": old_project_uid, "name": "HIST 110 – World History (Spring 2026)", "description": "Completed prerequisite, kept for reference.",
        "color": "gray", "icon": "\U0001F4DC", "cover_image_b64": None, "cover_image_type": None,
        "group_uid": pg_courses, "archived_at": (TODAY - timedelta(days=20)).isoformat() + "T00:00:00+00:00",
        "created_at": now_iso(), "updated_at": now_iso(),
    })

    # ---------------------------------------------------------------- #
    # Calendars, task lists, address books (multi-collection features)
    # ---------------------------------------------------------------- #
    print("  calendars / task lists / address books ...")
    cal_personal = "calendar"  # default
    cal_classes = "classes"
    cal_exams = "exams"
    cal_campus = "campus-life"
    db.upsert_calendar(conn, {"uid": cal_personal, "name": "Personal", "color": "blue", "created_at": now_iso()})
    db.upsert_calendar(conn, {"uid": cal_classes, "name": "Classes", "color": "green", "created_at": now_iso()})
    db.upsert_calendar(conn, {"uid": cal_exams, "name": "Exams & Deadlines", "color": "red", "created_at": now_iso()})
    db.upsert_calendar(conn, {"uid": cal_campus, "name": "Campus Life", "color": "purple", "created_at": now_iso()})

    tl_default = "tasks"  # default
    tl_cs301 = "cs301-assignments"
    tl_math241 = "math241-problem-sets"
    tl_phys210 = "phys210-labs"
    tl_capstone = "capstone-project"
    tl_studentgov = "student-gov"
    db.upsert_task_list(conn, {"uid": tl_default, "name": "Personal", "color": "gray", "created_at": now_iso()})
    db.upsert_task_list(conn, {"uid": tl_cs301, "name": "CS 301 Assignments", "color": "blue", "created_at": now_iso()})
    db.upsert_task_list(conn, {"uid": tl_math241, "name": "Math 241 Problem Sets", "color": "green", "created_at": now_iso()})
    db.upsert_task_list(conn, {"uid": tl_phys210, "name": "Physics Labs", "color": "purple", "created_at": now_iso()})
    db.upsert_task_list(conn, {"uid": tl_capstone, "name": "Capstone Project", "color": "red", "created_at": now_iso()})
    db.upsert_task_list(conn, {"uid": tl_studentgov, "name": "Student Gov", "color": "teal", "created_at": now_iso()})

    ab_default = "contacts"  # default
    ab_faculty = "faculty"
    db.upsert_addressbook(conn, {"uid": ab_default, "name": "Contacts", "color": "blue", "created_at": now_iso()})
    db.upsert_addressbook(conn, {"uid": ab_faculty, "name": "Faculty", "color": "orange", "created_at": now_iso()})

    # Link lists/calendars/addressbooks to their projects.
    db.set_calendar_project(conn, cal_classes, project_uids["capstone"])  # arbitrary anchor, classes span many
    db.set_calendar_project(conn, cal_campus, project_uids["studentgov"])
    db.set_task_list_project(conn, tl_cs301, project_uids["cs301"])
    db.set_task_list_project(conn, tl_math241, project_uids["math241"])
    db.set_task_list_project(conn, tl_phys210, project_uids["phys210"])
    db.set_task_list_project(conn, tl_capstone, project_uids["capstone"])
    db.set_task_list_project(conn, tl_studentgov, project_uids["studentgov"])
    db.set_addressbook_project(conn, ab_faculty, None)

    # ---------------------------------------------------------------- #
    # Contacts (faculty + classmates)
    # ---------------------------------------------------------------- #
    print("  contacts ...")
    faculty = [
        dict(name="Dr. Elena Marsh", org="Dept. of Computer Science", phone="+1-555-0101",
             email="e.marsh@fictional.edu", category="Professor", tags=["CS"], notes="CS 301 instructor. Office hours Mon/Wed 2-3pm, Eng Hall 410."),
        dict(name="Dr. Owen Whitfield", org="Dept. of Mathematics", phone="+1-555-0102",
             email="o.whitfield@fictional.edu", category="Professor", tags=["Math"], notes="MATH 241 instructor."),
        dict(name="Dr. Priya Anand", org="Dept. of Physics", phone="+1-555-0103",
             email="p.anand@fictional.edu", category="Professor", tags=["Physics"], notes="PHYS 210 instructor. Also runs the physics lab."),
        dict(name="Ms. Naomi Cole", org="Dept. of English", phone="+1-555-0104",
             email="n.cole@fictional.edu", category="Professor", tags=["Writing"], notes="ENG 150 instructor."),
        dict(name="Dr. Samuel Reyes", org="Office of Academic Advising", phone="+1-555-0105",
             email="s.reyes@fictional.edu", category="Advisor", tags=[], notes="Academic advisor -- annual plan review each September."),
        dict(name="Jordan Lee", org="Dept. of Computer Science", phone="+1-555-0106",
             email="jordan.lee@fictional.edu", category="TA", tags=["CS"], notes="CS 301 TA, runs the Friday lab section."),
    ]
    faculty_uids: dict[str, str] = {}
    for f in faculty:
        u = uid()
        faculty_uids[f["name"]] = u
        row = {
            "uid": u, "full_name": f["name"], "org": f["org"], "phone": f["phone"], "email": f["email"],
            "address": None, "category": f["category"], "tags": f["tags"], "notes": f["notes"],
            "photo_b64": None, "photo_type": None, "created_at": now_iso(), "updated_at": now_iso(),
            "addressbook_path": ab_faculty,
        }
        row = bridge.save_contact_row(row)
        db.upsert_contact(conn, row)

    classmates = [
        dict(name="Maya Chen", org=None, phone="+1-555-0201", email="maya.chen@fictional.edu",
             category="Classmate", tags=["CS", "Group Project"], notes="CS 301 study group, meets Sundays."),
        dict(name="Diego Fernandez", org=None, phone="+1-555-0202", email="diego.f@fictional.edu",
             category="Classmate", tags=["Capstone", "Group Project"], notes="Capstone project partner."),
        dict(name="Aisha Rahman", org=None, phone="+1-555-0203", email="aisha.r@fictional.edu",
             category="Classmate", tags=["Math"], notes="Math 241 study group."),
        dict(name="Ben Okafor", org=None, phone="+1-555-0204", email="ben.okafor@fictional.edu",
             category="Classmate", tags=[], notes="Co-treasurer, Student Government."),
    ]
    for c in classmates:
        u = uid()
        row = {
            "uid": u, "full_name": c["name"], "org": c["org"], "phone": c["phone"], "email": c["email"],
            "address": None, "category": c["category"], "tags": c["tags"], "notes": c["notes"],
            "photo_b64": None, "photo_type": None, "created_at": now_iso(), "updated_at": now_iso(),
            "addressbook_path": ab_default,
        }
        row = bridge.save_contact_row(row)
        db.upsert_contact(conn, row)

    # ---------------------------------------------------------------- #
    # Schedule: classes, holidays, settings -- then mirror to Calendar
    # ---------------------------------------------------------------- #
    print("  class schedule ...")
    db.save_schedule_settings(conn, {
        "semester_start": iso(SEMESTER_START), "semester_end": iso(SEMESTER_END),
        "credits_needed": 15, "reminder_minutes": 15,
    })
    db.set_schedule_target_calendar(conn, cal_classes)

    db.upsert_holiday(conn, {"uid": uid(), "label": "Fall Break", "date_from": "2026-10-12", "date_to": "2026-10-13"})
    db.upsert_holiday(conn, {"uid": uid(), "label": "Thanksgiving Break", "date_from": "2026-11-25", "date_to": "2026-11-29"})

    classes = [
        dict(day="Monday", start="10:00", end="11:30", name="Algorithms & Data Structures", acronym="CS301",
             class_type="Lecture", professor="Dr. Elena Marsh", room="Eng Hall 204", credits=4, parity="all"),
        dict(day="Wednesday", start="10:00", end="11:30", name="Algorithms & Data Structures", acronym="CS301",
             class_type="Lecture", professor="Dr. Elena Marsh", room="Eng Hall 204", credits=0, parity="all"),
        dict(day="Friday", start="13:00", end="15:00", name="Algorithms & Data Structures Lab", acronym="CS301L",
             class_type="Lab", professor="Jordan Lee", room="Computer Lab B", credits=0, parity="all"),
        dict(day="Tuesday", start="09:00", end="10:15", name="Linear Algebra", acronym="MATH241",
             class_type="Lecture", professor="Dr. Owen Whitfield", room="Math Building 101", credits=3, parity="all"),
        dict(day="Thursday", start="09:00", end="10:15", name="Linear Algebra", acronym="MATH241",
             class_type="Lecture", professor="Dr. Owen Whitfield", room="Math Building 101", credits=0, parity="all"),
        dict(day="Monday", start="13:00", end="14:15", name="Modern Physics", acronym="PHYS210",
             class_type="Lecture", professor="Dr. Priya Anand", room="Science Center 310", credits=3, parity="all"),
        dict(day="Wednesday", start="13:00", end="14:15", name="Modern Physics", acronym="PHYS210",
             class_type="Lecture", professor="Dr. Priya Anand", room="Science Center 310", credits=0, parity="all"),
        dict(day="Thursday", start="14:00", end="16:00", name="Modern Physics Lab", acronym="PHYS210L",
             class_type="Lab", professor="Dr. Priya Anand", room="Physics Lab 2", credits=1, parity="odd"),
        dict(day="Tuesday", start="11:00", end="12:15", name="Academic Writing", acronym="ENG150",
             class_type="Lecture", professor="Ms. Naomi Cole", room="Humanities 220", credits=3, parity="all"),
        dict(day="Thursday", start="11:00", end="12:15", name="Academic Writing", acronym="ENG150",
             class_type="Lecture", professor="Ms. Naomi Cole", room="Humanities 220", credits=0, parity="all"),
        dict(day="Friday", start="15:00", end="16:00", name="Capstone Seminar", acronym="CS499",
             class_type="Seminar", professor="Dr. Elena Marsh", room="Eng Hall 118", credits=2, parity="even"),
    ]

    schedule_settings_dict = db.get_schedule_settings(conn)
    holidays = db.list_holidays(conn)
    for c in classes:
        class_uid = uid()
        professor_contact_uid = faculty_uids.get(c["professor"])
        db.upsert_schedule_class(conn, {
            "uid": class_uid, "day": c["day"], "start_time": c["start"], "end_time": c["end"],
            "name": c["name"], "acronym": c["acronym"], "class_type": c["class_type"],
            "professor": c["professor"], "professor_contact_uid": professor_contact_uid,
            "room": c["room"], "credits": c["credits"], "parity": c["parity"], "enrolled": True,
            "event_uid": None, "created_at": now_iso(), "updated_at": now_iso(),
        })
        cls_row = db.get_schedule_class(conn, class_uid)
        event_row = class_to_event_row(cls_row, schedule_settings_dict, holidays)
        if event_row:
            event_row["tags"] = event_row.get("tags", []) + [
                {"CS301": "CS", "CS301L": "CS", "MATH241": "Math", "PHYS210": "Physics",
                 "PHYS210L": "Physics", "ENG150": "Writing", "CS499": "Capstone"}.get(c["acronym"], "Schedule"),
                "Schedule",
            ]
            saved = bridge.save_event_row(event_row)
            db.upsert_event(conn, saved)

    # ---------------------------------------------------------------- #
    # Tasks: assignments, subtasks, checklist, recurring, kanban mix
    # ---------------------------------------------------------------- #
    print("  tasks ...")

    def make_task(list_path, title, description, due_at, status="active", priority=None,
                   progress=None, tags=None, parent_uid=None, recurrence=None, start_at=None):
        t_uid = uid()
        row = {
            "uid": t_uid, "list_path": list_path, "title": title, "description": description,
            "start_at": start_at, "due_at": due_at, "priority": priority, "status": status,
            "progress": progress, "tags": tags or [], "parent_uid": parent_uid, "recurrence": recurrence,
            "created_at": now_iso(), "updated_at": now_iso(),
        }
        saved = bridge.save_task_row(row)
        saved["list_path"] = list_path  # bridge doesn't echo this back
        db.upsert_task(conn, saved)
        return t_uid

    # A couple of already-overdue items (relative to whenever this script
    # actually runs), to showcase the Overdue Tasks widget.
    make_task(tl_default, "Submit housing enrollment form", "Due to Residence Life before move-in.",
              iso(TODAY - timedelta(days=4)), status="waiting", priority=1, tags=["Urgent"])
    make_task(tl_default, "Complete online orientation module", "Title IX + academic integrity modules.",
              iso(TODAY - timedelta(days=2)), status="active", priority=2, tags=["Important"])

    # CS 301
    cs_proj = make_task(tl_cs301, "Problem Set 1: Big-O & Recurrences", "Chapters 1-3, submit via course portal.",
                         iso(SEMESTER_START + timedelta(days=10)), status="active", priority=2, tags=["CS", "Reading"])
    make_task(tl_cs301, "Problem Set 2: Trees & Heaps", "Implement a binary heap; written proofs for balance.",
              iso(SEMESTER_START + timedelta(days=24)), status="waiting", priority=2, tags=["CS"])
    ps3 = make_task(tl_cs301, "Problem Set 3: Graph Algorithms", "Dijkstra, BFS/DFS, and a written comparison.",
                     iso(SEMESTER_START + timedelta(days=38)), status="in_progress", priority=1, progress=0.4, tags=["CS", "Urgent"])
    db.add_checklist_item(conn, ps3, uid(), "Implement Dijkstra's algorithm", now_iso())
    db.add_checklist_item(conn, ps3, uid(), "Implement BFS/DFS", now_iso())
    db.add_checklist_item(conn, ps3, uid(), "Write comparison report", now_iso())
    db.toggle_checklist_item(conn, db.list_checklist_items(conn, ps3)[0]["uid"])
    make_task(tl_cs301, "Midterm review session", "Optional review with Jordan Lee.",
              iso(SEMESTER_START + timedelta(days=41)), status="active", priority=3, tags=["CS"])
    make_task(tl_cs301, "Final Project: Pathfinding Visualizer", "Group project with Maya Chen (3-person team).",
              iso(SEMESTER_END - timedelta(days=10)), status="waiting", priority=2, tags=["CS", "Group Project"])
    make_task(tl_cs301, "Lab 1: Recursion warm-up", "", iso(SEMESTER_START + timedelta(days=6)),
              status="done", priority=None, progress=1.0, tags=["CS", "Lab"])

    # Weekly recurring task
    make_task(tl_cs301, "Weekly reading response", "One-paragraph reading response due before each Monday lecture.",
              iso(SEMESTER_START), status="active", priority=3, tags=["CS", "Reading"],
              recurrence=f"FREQ=WEEKLY;UNTIL={iso(SEMESTER_END)}")

    # MATH 241
    make_task(tl_math241, "Homework 1: Vector Spaces", "", iso(SEMESTER_START + timedelta(days=9)),
              status="done", progress=1.0, tags=["Math"])
    make_task(tl_math241, "Homework 2: Matrix Operations", "", iso(SEMESTER_START + timedelta(days=23)),
              status="in_progress", priority=2, progress=0.6, tags=["Math"])
    make_task(tl_math241, "Homework 3: Eigenvalues & Eigenvectors", "Study group with Aisha Rahman Sunday before.",
              iso(SEMESTER_START + timedelta(days=37)), status="waiting", priority=2, tags=["Math", "Group Project"])
    make_task(tl_math241, "Midterm Exam", "Covers chapters 1-5.", iso(SEMESTER_START + timedelta(days=45)),
              status="active", priority=1, tags=["Math", "Urgent"])

    # PHYS 210
    make_task(tl_phys210, "Lab Report 1: Photoelectric Effect", "", iso(SEMESTER_START + timedelta(days=15)),
              status="done", progress=1.0, tags=["Physics", "Lab"])
    make_task(tl_phys210, "Lab Report 2: Wave-Particle Duality", "", iso(SEMESTER_START + timedelta(days=29)),
              status="in_progress", priority=2, progress=0.2, tags=["Physics", "Lab"])
    make_task(tl_phys210, "Problem Set: Special Relativity", "", iso(SEMESTER_START + timedelta(days=20)),
              status="active", priority=2, tags=["Physics"])

    # ENG 150
    eng_essay = make_task(tl_default, "Essay 1 Draft: Rhetorical Analysis", "Bring printed draft for peer review.",
                           iso(SEMESTER_START + timedelta(days=12)), status="active", priority=2, tags=["Writing"])
    db.add_checklist_item(conn, eng_essay, uid(), "Choose a text to analyze", now_iso())
    db.add_checklist_item(conn, eng_essay, uid(), "Outline thesis + 3 supporting points", now_iso())
    db.add_checklist_item(conn, eng_essay, uid(), "Write full draft", now_iso())
    db.add_checklist_item(conn, eng_essay, uid(), "Peer review exchange", now_iso())
    for item in db.list_checklist_items(conn, eng_essay)[:2]:
        db.toggle_checklist_item(conn, item["uid"])

    # Capstone project: a parent task with real subtasks (not just checklist)
    capstone_parent = make_task(tl_capstone, "Capstone Project: Campus Room-Booking App", "Two-semester project with Diego Fernandez.",
                                 iso(SEMESTER_END - timedelta(days=3)), status="in_progress", priority=1, progress=0.3, tags=["Capstone", "Group Project"])
    make_task(tl_capstone, "Proposal & advisor sign-off", "2-page proposal, needs Dr. Marsh's approval.",
              iso(SEMESTER_START + timedelta(days=14)), status="done", progress=1.0, tags=["Capstone"], parent_uid=capstone_parent)
    make_task(tl_capstone, "Literature review", "Survey 8-10 related booking-system papers.",
              iso(SEMESTER_START + timedelta(days=35)), status="in_progress", priority=2, progress=0.5, tags=["Capstone", "Reading"], parent_uid=capstone_parent)
    make_task(tl_capstone, "Prototype build", "Working prototype with auth + booking flow.",
              iso(SEMESTER_START + timedelta(days=70)), status="waiting", priority=2, tags=["Capstone"], parent_uid=capstone_parent)
    make_task(tl_capstone, "Final report & presentation", "", iso(SEMESTER_END - timedelta(days=3)),
              status="waiting", priority=1, tags=["Capstone"], parent_uid=capstone_parent)

    # Student Government
    make_task(tl_studentgov, "Draft fall semester club funding budget", "Coordinate with Ben Okafor.",
              iso(SEMESTER_START + timedelta(days=5)), status="active", priority=2, tags=["Group Project"])
    make_task(tl_studentgov, "Approve Career Fair co-sponsorship", "", iso(SEMESTER_START + timedelta(days=18)),
              status="waiting", priority=3)
    make_task(tl_studentgov, "Submit Q3 treasury report", "", iso(SEMESTER_START + timedelta(days=60)),
              status="waiting", priority=2, tags=["Urgent"])

    # ---------------------------------------------------------------- #
    # Events: exams/deadlines + campus life (classes already mirrored)
    # ---------------------------------------------------------------- #
    print("  events ...")

    def make_event(calendar_path, title, description, start_at, end_at, location=None, tags=None, reminders=None):
        row = {
            "uid": uid(), "calendar_path": calendar_path, "title": title, "description": description,
            "start_at": start_at, "end_at": end_at, "all_day": False, "location": location,
            "meeting_url": None, "status": "active", "recurrence": None, "exdates": [],
            "reminders": reminders or [], "tags": tags or [], "created_at": now_iso(), "updated_at": now_iso(),
        }
        saved = bridge.save_event_row(row)
        db.upsert_event(conn, saved)

    make_event(cal_exams, "CS 301 Midterm Exam", "Covers weeks 1-6.",
               f"{iso(SEMESTER_START + timedelta(days=41))}T10:00:00", f"{iso(SEMESTER_START + timedelta(days=41))}T11:30:00",
               location="Eng Hall 204", tags=["CS", "Urgent"], reminders=[1440, 60])
    make_event(cal_exams, "MATH 241 Midterm Exam", "",
               f"{iso(SEMESTER_START + timedelta(days=45))}T09:00:00", f"{iso(SEMESTER_START + timedelta(days=45))}T10:15:00",
               location="Math Building 101", tags=["Math", "Urgent"], reminders=[1440])
    make_event(cal_exams, "Final Exams Week Begins", "All finals per registrar schedule.",
               f"{iso(SEMESTER_END - timedelta(days=6))}T00:00:00", f"{iso(SEMESTER_END - timedelta(days=6))}T23:59:00",
               tags=["Urgent"], reminders=[10080])
    make_event(cal_exams, "CS 301 Final Exam", "Cumulative.",
               f"{iso(SEMESTER_END - timedelta(days=2))}T09:00:00", f"{iso(SEMESTER_END - timedelta(days=2))}T11:00:00",
               location="Eng Hall 204", tags=["CS", "Urgent"], reminders=[1440, 60])
    make_event(cal_campus, "Fall Career Fair", "Bring resumes; business casual.",
               f"{iso(SEMESTER_START + timedelta(days=18))}T11:00:00", f"{iso(SEMESTER_START + timedelta(days=18))}T15:00:00",
               location="Student Union Ballroom", tags=["Important"], reminders=[1440])
    make_event(cal_campus, "Student Government Budget Meeting", "Monthly senate meeting.",
               f"{iso(SEMESTER_START + timedelta(days=7))}T18:00:00", f"{iso(SEMESTER_START + timedelta(days=7))}T19:30:00",
               location="Union Room 220", reminders=[60])
    make_event(cal_campus, "CS Club Kickoff Social", "", f"{iso(SEMESTER_START + timedelta(days=3))}T17:00:00",
               f"{iso(SEMESTER_START + timedelta(days=3))}T19:00:00", location="Eng Hall Courtyard", tags=["CS"])
    make_event(cal_personal, "Gym", "Recurring personal workout block.",
               f"{iso(TODAY + timedelta(days=1))}T07:00:00", f"{iso(TODAY + timedelta(days=1))}T08:00:00")

    # ---------------------------------------------------------------- #
    # Habits + entries (heatmap/streaks)
    # ---------------------------------------------------------------- #
    print("  habits ...")
    habits = [
        dict(name="Study 1h/day", description="At least one focused hour outside class.", color="blue",
             icon="\U0001F4DA", target=1, project=project_uids["capstone"], p_done=0.72),
        dict(name="Attend Lectures", description="Show up -- every lecture counts.", color="green",
             icon="\U0001F393", target=1, project=None, p_done=0.85),
        dict(name="Sleep 7+ Hours", description="", color="purple", icon="\U0001F634", target=1, project=None, p_done=0.55),
        dict(name="Drink Water (8 glasses)", description="", color="teal", icon="\U0001F4A7", target=8, project=None, p_done=None),
    ]
    habit_uids = []
    for h in habits:
        h_uid = uid()
        habit_uids.append((h_uid, h))
        db.upsert_habit(conn, {
            "uid": h_uid, "name": h["name"], "description": h["description"], "color": h["color"],
            "icon": h["icon"], "target_per_day": h["target"], "tags": [], "project_uid": h["project"],
            "archived_at": None, "created_at": now_iso(), "updated_at": now_iso(),
        })

    history_start = TODAY - timedelta(days=45)
    for h_uid, h in habit_uids:
        d = history_start
        while d <= TODAY:
            if h["target"] > 1:
                # Quantity habit: usually 4-8 glasses, occasional 0.
                value = 0 if RNG.random() < 0.1 else RNG.randint(3, 8)
            else:
                value = 1 if RNG.random() < h["p_done"] else 0
            if value > 0:
                db.upsert_habit_entry(conn, h_uid, iso(d), float(value), None, now_iso())
            d += timedelta(days=1)

    # ---------------------------------------------------------------- #
    # Custom databases: grade tracker (formulas) + reading list (simple)
    # ---------------------------------------------------------------- #
    print("  custom databases ...")
    grades_db = uid()
    db.upsert_database(conn, {
        "uid": grades_db, "name": "Course Grades", "description": "Weighted grade tracking across this semester's courses.",
        "color": "blue", "icon": "\U0001F4CA", "tags": ["CS", "Math", "Physics", "Writing"], "project_uid": None,
        "archived_at": None, "created_at": now_iso(), "updated_at": now_iso(),
    })
    col_course = uid()
    col_assignment = uid()
    col_category = uid()
    col_grade = uid()
    col_weight = uid()
    col_weighted = uid()
    col_due = uid()
    col_submitted = uid()
    db.upsert_database_column(conn, {"uid": col_course, "database_uid": grades_db, "name": "Course", "type": "select",
                                      "formula": None, "summary_formula": None,
                                      "options": ["CS301", "MATH241", "PHYS210", "ENG150"], "position": 0, "created_at": now_iso()})
    db.upsert_database_column(conn, {"uid": col_assignment, "database_uid": grades_db, "name": "Assignment", "type": "text",
                                      "formula": None, "summary_formula": None, "options": [], "position": 1, "created_at": now_iso()})
    db.upsert_database_column(conn, {"uid": col_category, "database_uid": grades_db, "name": "Category", "type": "select",
                                      "formula": None, "summary_formula": None,
                                      "options": ["Homework", "Quiz", "Midterm", "Final", "Project", "Lab"], "position": 2, "created_at": now_iso()})
    db.upsert_database_column(conn, {"uid": col_grade, "database_uid": grades_db, "name": "Grade", "type": "number",
                                      "formula": None, "summary_formula": "WEIGHTAVG(Grade, Weight)", "options": [], "position": 3, "created_at": now_iso()})
    db.upsert_database_column(conn, {"uid": col_weight, "database_uid": grades_db, "name": "Weight", "type": "number",
                                      "formula": None, "summary_formula": "SUM(Weight)", "options": [], "position": 4, "created_at": now_iso()})
    # No summary_formula on this column: a summary formula is evaluated
    # against each row's *stored* values (routers/databases.py's
    # _summary_row), and a formula-type column has no stored value --
    # only a live-computed one -- so aggregating over it would always
    # render as an error footer. Per-row formula only.
    db.upsert_database_column(conn, {"uid": col_weighted, "database_uid": grades_db, "name": "Weighted Points", "type": "formula",
                                      "formula": "Grade * Weight", "summary_formula": None, "options": [], "position": 5, "created_at": now_iso()})
    db.upsert_database_column(conn, {"uid": col_due, "database_uid": grades_db, "name": "Due Date", "type": "date",
                                      "formula": None, "summary_formula": None, "options": [], "position": 6, "created_at": now_iso()})
    db.upsert_database_column(conn, {"uid": col_submitted, "database_uid": grades_db, "name": "Submitted", "type": "checkbox",
                                      "formula": None, "summary_formula": None, "options": [], "position": 7, "created_at": now_iso()})

    grade_rows = [
        ("CS301", "Problem Set 1", "Homework", 94, 0.05, iso(SEMESTER_START + timedelta(days=10)), True),
        ("CS301", "Lab 1: Recursion", "Lab", 100, 0.05, iso(SEMESTER_START + timedelta(days=6)), True),
        ("CS301", "Problem Set 2", "Homework", 88, 0.05, iso(SEMESTER_START + timedelta(days=24)), True),
        ("CS301", "Problem Set 3", "Homework", None, 0.05, iso(SEMESTER_START + timedelta(days=38)), False),
        ("MATH241", "Homework 1", "Homework", 91, 0.1, iso(SEMESTER_START + timedelta(days=9)), True),
        ("MATH241", "Homework 2", "Homework", None, 0.1, iso(SEMESTER_START + timedelta(days=23)), False),
        ("MATH241", "Quiz 1", "Quiz", 85, 0.05, iso(SEMESTER_START + timedelta(days=16)), True),
        ("PHYS210", "Lab Report 1", "Lab", 96, 0.1, iso(SEMESTER_START + timedelta(days=15)), True),
        ("PHYS210", "Lab Report 2", "Lab", None, 0.1, iso(SEMESTER_START + timedelta(days=29)), False),
        ("ENG150", "Essay 1 Draft", "Homework", 89, 0.15, iso(SEMESTER_START + timedelta(days=12)), False),
        ("ENG150", "Diagnostic Quiz", "Quiz", 100, 0.05, iso(SEMESTER_START + timedelta(days=2)), True),
    ]
    for i, (course, assignment, category, grade, weight, due, submitted) in enumerate(grade_rows):
        db.upsert_database_row(conn, {
            "uid": uid(), "database_uid": grades_db,
            "values": {col_course: course, col_assignment: assignment, col_category: category,
                       col_grade: grade, col_weight: weight, col_due: due, col_submitted: submitted},
            "position": float(i), "created_at": now_iso(), "updated_at": now_iso(),
        })

    reading_db = uid()
    db.upsert_database(conn, {
        "uid": reading_db, "name": "Reading List", "description": "Assigned readings across all courses this term.",
        "color": "teal", "icon": "\U0001F4D6", "tags": ["Reading"], "project_uid": None,
        "archived_at": None, "created_at": now_iso(), "updated_at": now_iso(),
    })
    r_book = uid()
    r_course = uid()
    r_pages = uid()
    r_read = uid()
    db.upsert_database_column(conn, {"uid": r_book, "database_uid": reading_db, "name": "Title", "type": "text",
                                      "formula": None, "summary_formula": None, "options": [], "position": 0, "created_at": now_iso()})
    db.upsert_database_column(conn, {"uid": r_course, "database_uid": reading_db, "name": "Course", "type": "select",
                                      "formula": None, "summary_formula": None,
                                      "options": ["CS301", "MATH241", "PHYS210", "ENG150"], "position": 1, "created_at": now_iso()})
    db.upsert_database_column(conn, {"uid": r_pages, "database_uid": reading_db, "name": "Pages", "type": "number",
                                      "formula": None, "summary_formula": "SUM(Pages)", "options": [], "position": 2, "created_at": now_iso()})
    db.upsert_database_column(conn, {"uid": r_read, "database_uid": reading_db, "name": "Read", "type": "checkbox",
                                      "formula": None, "summary_formula": None, "options": [], "position": 3, "created_at": now_iso()})
    reading_rows = [
        ("Introduction to Algorithms (ch. 1-4)", "CS301", 120, True),
        ("Introduction to Algorithms (ch. 5-8)", "CS301", 140, False),
        ("Linear Algebra and Its Applications (ch. 1-3)", "MATH241", 90, True),
        ("Six Ideas That Shaped Physics (Unit R)", "PHYS210", 75, False),
        ("They Say / I Say (ch. 1-2)", "ENG150", 50, True),
        ("They Say / I Say (ch. 3-5)", "ENG150", 60, False),
    ]
    for i, (title, course, pages, read) in enumerate(reading_rows):
        db.upsert_database_row(conn, {
            "uid": uid(), "database_uid": reading_db,
            "values": {r_book: title, r_course: course, r_pages: pages, r_read: read},
            "position": float(i), "created_at": now_iso(), "updated_at": now_iso(),
        })

    # ---------------------------------------------------------------- #
    # Dashboard widgets -- one of every type
    # ---------------------------------------------------------------- #
    print("  dashboard widgets ...")
    widget_specs = [
        ("today_agenda", None, {"width": "half"}),
        ("mini_month_calendar", None, {"width": "half"}),
        ("weekly_overview", None, {"width": "full"}),
        ("upcoming_events", "Upcoming Deadlines", {"width": "third", "range_days": 14}),
        ("overdue_tasks", None, {"width": "third"}),
        ("project_preview", None, {"width": "third"}),
        ("habit_checkin", None, {"width": "half"}),
    ]
    for i, (wtype, title, config) in enumerate(widget_specs):
        db.upsert_dashboard_widget(conn, {
            "uid": uid(), "type": wtype, "title": title, "config": config,
            "position": float(i), "created_at": now_iso(), "group_uid": None,
        })
    # This dashboard already has a mini_month_calendar from the loop above,
    # so mark the one-time backfill migration as already done -- otherwise
    # the app would insert a second one the first time the Dashboard loads.
    db.set_app_meta(conn, "dashboard_mini_calendar_backfilled_v1", "1")


def main() -> int:
    print("== University demo data seed ==")
    print(f"Working dir: {WEBAPP_DIR}")

    settings = load_settings()
    print(f"Radicale:    {settings.radicale_base_url}")
    print(f"SQLite:      {settings.db_path}")
    print()

    print("Step 1/4: backing up + resetting storage ...")
    collections_dir = backup_and_reset_radicale_storage()
    backup_sqlite_cache(settings.db_path)

    print("Step 2/4: starting throwaway Radicale ...")
    radicale = start_radicale(collections_dir)
    try:
        print("Step 3/4: writing university dataset ...")
        bridge = CalDavBridge(settings)
        with db.connect(settings.db_path) as conn:
            build(conn, bridge)
            print("  reconciling sqlite cache with Radicale (full_refresh) ...")
            sync.full_refresh(bridge, conn)

            counts = {
                "events": len(db.list_events(conn)),
                "tasks": len(db.list_tasks(conn)),
                "contacts": len(db.list_contacts(conn)),
                "projects": len(db.list_projects(conn, include_archived=True)),
                "tags": len(db.list_tags(conn)),
                "habits": len(db.list_habits(conn)),
                "databases": len(db.list_databases(conn)),
                "schedule_classes": len(db.list_schedule_classes(conn)),
                "dashboard_widgets": len(db.list_dashboard_widgets(conn)),
            }
        print("\nStep 4/4: done. Row counts:")
        for k, v in counts.items():
            print(f"  {k:20s} {v}")
    finally:
        print("\nStopping throwaway Radicale ...")
        radicale.terminate()
        try:
            radicale.wait(timeout=10)
        except subprocess.TimeoutExpired:
            radicale.kill()

    print("\nDone. Start the app normally (./run.sh) to see the new data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
