"""Core tests for the testing conventions (rules/testing-conventions.md).

A test never asserts on the text of CSS, template or script source. Files that
still do are listed in LEGACY_SOURCE_TEXT_TESTS; the list only shrinks, and a
rule is done when it is empty.
"""

import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent.parent
SOURCE_READ = re.compile(r"read_text\(|open\([^)]*(?:\.css|\.html|\.js)")

LEGACY_SOURCE_TEXT_TESTS: set[str] = {
    "test_bulk_actions_tables.py",
    "test_calendar_month_bars.py",
    "test_calendar_nav_labels.py",
    "test_calendar_ui_audit_fixes.py",
    "test_calendar_week_allday_boundary_drag.py",
    "test_calendar_week_scheduling.py",
    "test_calendar_week_scroll_restore.py",
    "test_data_health.py",
    "test_date_time_fields.py",
    "test_env_file.py",
    "test_event_format_field.py",
    "test_habit_archive.py",
    "test_habit_audit_fixes.py",
    "test_habits_page.py",
    "test_holiday_date_sync.py",
    "test_icon_library_lucide.py",
    "test_image_cropper_ratio.py",
    "test_inline_field_validation.py",
    "test_label_ui_audit.py",
    "test_modal_csp.py",
    "test_modal_footer_and_inputs.py",
    "test_modal_input_phaseC_swatch_grid.py",
    "test_modal_uniformization.py",
    "test_page_header_narrow.py",
    "test_phase5_contacts.py",
    "test_project_detail.py",
    "test_published_lists_create_button.py",
    "test_push.py",
    "test_pwa_shell.py",
    "test_responsive_tables.py",
    "test_security_headers.py",
    "test_sidebar_tree.py",
    "test_tasks_table_labels_status_title.py",
    "test_toast_rework.py",
    "test_ui_audit_flat_2026_09_25.py",
    "test_view_edit_merge.py",
    "test_widget_library.py",
}


def _files_reading_source() -> set[str]:
    found = set()
    for path in TESTS_DIR.rglob("test_*.py"):
        if path.parent.name == "core":
            continue
        if SOURCE_READ.search(path.read_text()):
            found.add(path.name)
    return found


def test_no_new_test_asserts_on_source_text():
    offenders = _files_reading_source() - LEGACY_SOURCE_TEXT_TESTS
    assert not offenders, f"Tests must not read source files: {sorted(offenders)}"


def test_legacy_list_has_no_stale_entries():
    stale = LEGACY_SOURCE_TEXT_TESTS - _files_reading_source()
    assert not stale, f"Remove from LEGACY_SOURCE_TEXT_TESTS (fixed): {sorted(stale)}"
