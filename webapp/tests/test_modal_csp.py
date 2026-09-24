"""2026-09-24 CSP fix: modal.js parses a fetched full page with DOMParser,
whose document inherits the host page's CSP -- the fetched head's
`<style nonce>` (a *different* response's nonce) logged a style-src-elem
violation on every modal open. modal.js strips <style> blocks first.
Found and confirmed live via Playwright's securitypolicyviolation event."""

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"


def test_modal_strips_style_blocks_before_parsing():
    js = (_STATIC / "modal.js").read_text()
    assert "STYLE_BLOCK_RE = /<style\\b[^>]*>[\\s\\S]*?<\\/style\\s*>/gi" in js
    assert 'parseFromString(html.replace(STYLE_BLOCK_RE, ""), "text/html")' in js
    # No other unstripped full-page parse left in modal.js.
    assert js.count("parseFromString(") == 1


def test_base_template_style_still_nonced():
    # The fix must not loosen the policy: base.html's one inline <style>
    # keeps its per-response nonce.
    base = (_STATIC.parent / "templates" / "base.html").read_text()
    assert '<style nonce="{{ csp_nonce() }}">' in base
