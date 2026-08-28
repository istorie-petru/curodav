"""Tests for the 2026-08-15 Modal window uniformization slices (A-H,
plans/open.md's own numbering):

- Slice A/B: habit_form.html, habit_task_form.html, label_edit_modal.html,
  label_merge_modal.html, note_form.html, and quick_add.html all used to
  hand-roll their own `.modal-footer` markup instead of including the
  shared `_modal_footer.html` partial the core three entities (task/event/
  contact) already used -- see plans/open.md's Modal window uniformization
  section for the full audit. They're migrated onto the shared partial
  here, which also folds in slice A: note_form.html's Delete had neither
  `data-confirm-sheet` nor `data-delete-undo` at all before this slice --
  the only unconfirmed destructive action anywhere in the app -- and now
  goes through `_modal_footer.html`'s `confirm` mode like every other
  migrated modal's Delete.
- Slice C: the "New widget" triggers (dashboard.html, label_detail.html)
  open the same two-pane `.widget-builder` grid `_widget_edit_modal.html`'s
  own trigger already opens `data-modal-size="wide"` for -- they now carry
  the same attribute so the dialog doesn't squeeze the grid into the
  default width.
- Slice D: `_modal_widget_customize.html` (the widget builder's "Add
  widget" primary-only footer, no back link at all -- extended
  `_modal_footer.html` to support omitting `footer_back_url` entirely).
- Slice E: `_widget_edit_modal.html` gets a Back/Done-only footer (no
  primary -- extended the partial to support omitting
  `footer_primary_label`); the real Save stays in the body as
  `_widget_edit_form.html`'s own progressive-enhancement fallback button
  for the no-JS/autosave-failed path.
- Slice F: `banner_editor.html` gets a Back/Done-only footer using the
  real `page_url` (this template also renders as a standalone no-JS page).
- Slice G: the icon prefix is dropped from `banner_editor.html`'s and
  `_widget_edit_modal.html`'s `<h1>` to match every other utility modal's
  plain-title convention."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import banners as banners_router
from src.routers import dashboard as dashboard_router
from src.routers import habits as habits_router
from src.routers import labels as labels_router
from src.routers import notes as notes_router
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/"):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "root_path": "",
            "headers": [],
        }
    )


class TestHabitFormFooter:
    def test_edit_habit_uses_shared_footer_with_confirm_delete(self, conn):
        db.upsert_habit(conn, {"uid": "h1", "name": "Read"})
        body = habits_router.edit_habit_form("h1", _request(), conn=conn).body.decode()
        assert 'class="detail-delete-link"' in body
        assert 'class="btn danger"' not in body  # old filled-red button is gone
        assert "data-confirm-sheet=" in body
        assert "/habits/h1/delete" in body
        assert 'form="habit-form"' in body

    def test_new_habit_has_no_delete_but_has_shared_footer(self, conn):
        body = habits_router.new_habit_form(_request(), conn=conn).body.decode()
        assert "detail-delete-link" not in body
        assert 'form="habit-form"' in body
        assert 'class="modal-footer"' in body


class TestHabitTaskFormFooter:
    def test_new_habit_task_uses_shared_footer(self, conn):
        body = tasks_router.new_task_form(_request(), habit=True, conn=conn).body.decode()
        assert 'form="habit-task-form"' in body
        assert '<a href="/tasks/habits" class="btn ghost" data-modal-cancel>' in body


class TestLabelEditModalFooter:
    def test_edit_label_uses_shared_footer_with_confirm_delete(self, conn):
        body = labels_router.edit_label_modal("work", _request(), conn=conn).body.decode()
        assert 'class="detail-delete-link"' in body
        assert 'class="btn danger"' not in body
        assert "data-confirm-sheet=" in body
        assert "/labels/work/delete" in body
        assert 'form="label-form"' in body


class TestLabelMergeModalFooter:
    def test_merge_modal_uses_shared_footer_no_delete(self, conn):
        db.upsert_label_config(conn, {"name": "other"})
        body = labels_router.merge_modal("work", _request(), conn=conn).body.decode()
        assert "detail-delete-link" not in body
        assert 'form="label-merge-form"' in body
        assert "Merge" in body


class TestNoteFormFooter:
    def test_edit_note_delete_is_now_confirmed(self, conn):
        db.upsert_note(conn, {"uid": "n1", "content": "hi", "created_at": _now(), "updated_at": _now()})
        body = notes_router.edit_note_form("n1", _request(), conn=conn).body.decode()
        assert 'class="detail-delete-link"' in body
        assert 'class="btn danger"' not in body
        # the actual safety fix: some confirmation mechanism now guards
        # the delete POST, where before this slice there was none at all.
        assert "data-confirm-sheet=" in body
        assert "/notes/n1/delete" in body

    def test_new_note_has_no_delete(self, conn):
        body = notes_router.new_note_form(_request(), conn=conn).body.decode()
        assert "detail-delete-link" not in body
        assert 'form="note-form"' in body


class TestQuickAddFooter:
    def test_quick_add_uses_shared_footer_and_keeps_save_id(self, conn):
        body = dashboard_router.quick_add_form(_request(), conn=conn).body.decode()
        # static/quick_add.js retargets the Save button's `form` attribute
        # on tab switch via getElementById("quick-add-save") -- the shared
        # partial must still expose that id.
        assert 'id="quick-add-save"' in body
        assert 'form="task-form"' in body
        assert "detail-delete-link" not in body


class TestNewWidgetTriggerWideSizing:
    def test_new_widget_trigger_carries_wide_attribute(self, conn):
        # "New widget" only renders in edit mode (dashboard.html's own
        # {% if edit_mode %} gate).
        body = dashboard_router.dashboard_view(_request("/?edit=1"), edit=True, conn=conn).body.decode()
        # the New widget link must open the same wide dialog
        # _widget_edit_modal.html's own trigger already opens.
        assert "/dashboard/customize" in body
        idx = body.index("/dashboard/customize")
        surrounding = body[max(0, idx - 40) : idx + 200]
        assert 'data-modal-size="wide"' in surrounding


class TestWidgetCustomizeModalFooter:
    def test_customize_modal_is_primary_only_no_back_link(self, conn):
        body = dashboard_router.dashboard_customize(_request(), conn=conn).body.decode()
        assert 'class="modal-footer"' in body
        assert 'form="widget-builder-form"' in body
        assert "Add widget" in body
        # deliberately no back/cancel link at all -- the dialog's own X
        # closes it (2026-08-07 "one button" decision, preserved by slice D).
        assert "data-modal-cancel" not in body
        assert "detail-delete-link" not in body
        # plain title, no icon prefix -- rule 3.
        assert "<h1>Customize" in body


class TestWidgetEditModalFooter:
    def test_widget_edit_modal_has_done_only_footer(self, conn):
        dashboard_router.add_widget(
            source="calendar_tasks", view="agenda", range="today", title="", project_uid="",
            tags="", task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn,
        )
        widget = db.list_dashboard_widgets(conn)[-1]
        body = dashboard_router.widget_edit_form(_request(), widget["uid"], conn=conn).body.decode()
        assert 'class="modal-footer"' in body
        assert "Done" in body
        # no second Save in the footer -- the real one is still the body's
        # own progressive-enhancement fallback button (widget-save-filters-btn).
        assert 'form="widget-builder-form"' not in body
        assert "widget-save-filters-btn" in body
        # plain title, no icon prefix -- rule 3.
        assert "<h1>Edit widget</h1>" in body


class TestBannerEditorFooter:
    def test_banner_editor_has_done_only_footer_with_real_page_url(self, conn):
        body = banners_router.banner_editor(_request(), scope="", page_url="/dashboard", conn=conn).body.decode()
        assert 'class="modal-footer"' in body
        assert 'href="/dashboard"' in body
        assert "Done" in body
        assert "detail-delete-link" not in body
        # plain title, no icon prefix -- rule 3.
        assert "<h1>Page banner</h1>" in body


class TestFullAppModalSweep:
    """Slice H: regression guard that every modal fragment in the app
    routes its footer through `_modal_footer.html` -- no leftover
    hand-rolled `.modal-footer` markup anywhere."""

    def test_every_modal_template_includes_shared_footer(self):
        from pathlib import Path

        templates_dir = Path(__file__).resolve().parents[1] / "src" / "templates"
        modal_files = [
            "contact_detail.html", "contact_form.html", "event_detail.html", "event_form.html",
            "habit_form.html", "habit_task_form.html", "label_edit_modal.html", "label_merge_modal.html",
            "note_form.html", "quick_add.html", "task_detail.html", "task_form.html",
            "banner_editor.html", "_widget_edit_modal.html", "_modal_widget_customize.html",
        ]
        for name in modal_files:
            text = (templates_dir / name).read_text()
            assert '{% include "_modal_footer.html" %}' in text, f"{name} doesn't use the shared footer partial"
