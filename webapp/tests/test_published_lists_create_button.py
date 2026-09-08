"""Direct bug report, 2026-09-08: "published list doesn't work to create
even if labels exists. though this should not be a condition." --
published_lists.js's create-modal form validation used to disable the
"Publish List" submit button until BOTH a name was typed AND at least one
label checkbox was ticked, even though the server (routers/published_lists.
py's create_list()) has never required a label -- `labels: list[str] =
Form([])` defaults to empty, and _filter_from_form()/evaluate_label_filter()
both handle an empty filter without error (see
test_phase6_published_lists.py's test_create_slugifies_name_and_dedupes_
collection_path, which already calls create_list(..., labels=[], ...)
directly and asserts success). The stricter client-side gate meant the
button silently never enabled for a labelless list even when labels DID
exist in the account -- no error shown anywhere, since this was a
disabled-button UI gate, not a validation message.

Fix: static/published_lists.js's checkValidity() no longer factors in
`hasLabel` -- only the name field gates the button now, matching the
server's own actual requirement. No JS unit-test harness for static/*.js
in this repo (same gap every prior JS-only slice's own test file notes) --
covered via `node --check` (syntax) plus a source grep pinning that the
label-checkbox state is no longer part of the disabled condition.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent.parent / "src" / "static"


class TestCreateButtonNotGatedOnLabels:
    def test_script_is_valid_js(self):
        subprocess.run(["node", "--check", str(_STATIC_DIR / "published_lists.js")], check=True)

    def test_disabled_state_depends_only_on_name(self):
        script = (_STATIC_DIR / "published_lists.js").read_text()
        assert "submitBtn.disabled = !hasName;" in script
        # The old bug: disabling on `!(hasName && hasLabel)` must be gone,
        # not just shadowed by a second assignment.
        assert "hasLabel" not in script
