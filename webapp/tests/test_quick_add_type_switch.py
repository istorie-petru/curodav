"""The Add new modal's type dropdown switches the panels even though its open dropdown is moved out of the modal.

There is no JS test harness in this repo, so this runs static/quick_add.js under node with a minimal fake DOM in which
the radio that fires `change` lives outside the panels container, as it does while the dropdown is open
(#multiselect-portal)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "src" / "static" / "quick_add.js"

HARNESS = r"""
const listeners = {};
const mk = (extra) => Object.assign({ dataset: {}, classList: { toggle() {} }, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; } }, extra);
const panels = ["task", "event", "note"].map((k) => mk({ dataset: { quickAddPanel: k } }));
const ownRadios = {};
const container = mk({
  dataset: { active: "task" },
  querySelectorAll: () => panels,
  querySelector: (sel) => { const m = /data-quick-add-panel="(\w+)"/.exec(sel); return m ? ownRadios[m[1]] : null; },
});
["task", "event", "note"].forEach((k) => { ownRadios[k] = mk({ checked: k === "task", dataset: { quickAddTab: k }, dispatchEvent() {} }); });
const save = mk({});
global.document = {
  addEventListener: (type, fn) => { listeners[type] = fn; },
  querySelector: () => null,
  querySelectorAll: () => [],
  getElementById: (id) => (id === "quick-add-panels" ? container : id === "quick-add-save" ? save : null),
};
global.window = { matchMedia: () => ({ matches: false, addEventListener() {} }) };
require(process.argv[1]);
window.CCQuickAdd.init();
// The radio that fires the change is NOT inside the container (it was portaled out with its dropdown panel).
const portaled = mk({ checked: true, dataset: { quickAddTab: "event" }, matches: (s) => s === "input[data-quick-add-tab]" });
listeners.change({ target: portaled });
console.log(JSON.stringify({ active: container.dataset.active, form: save.attrs.form }));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_switching_type_works_when_the_dropdown_radio_is_outside_the_modal():
    out = subprocess.run(["node", "-e", HARNESS, str(SCRIPT)], capture_output=True, text=True, check=True).stdout
    assert '"active":"event"' in out and '"form":"event-form"' in out
