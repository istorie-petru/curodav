// Published Lists page interactions: copy-to-clipboard, form validation

(function () {
    // Copy to clipboard functionality
    function initCopyButtons() {
        document.querySelectorAll('.copy-link-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var url = this.getAttribute('data-url');
                if (!url) return;

                navigator.clipboard.writeText(url).then(function () {
                    showCopyFeedback(btn);
                }).catch(function () {
                    fallbackCopy(url, btn);
                });
            });
        });
    }

    function showCopyFeedback(btn) {
        var originalHTML = btn.innerHTML;
        btn.innerHTML = '<svg class="icon icon-sm" aria-hidden="true"><use href="#icon-check-square"></use></svg>';
        btn.classList.add('copied');
        btn.setAttribute('aria-label', 'Copied!');
        btn.title = 'Copied!';

        setTimeout(function () {
            btn.innerHTML = originalHTML;
            btn.classList.remove('copied');
            btn.setAttribute('aria-label', 'Copy link');
            btn.title = 'Copy link';
        }, 2000);
    }

    function fallbackCopy(text, btn) {
        var textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        try {
            document.execCommand('copy');
            showCopyFeedback(btn);
        } catch (e) {
            window.ccToast({ message: 'Could not copy link', variant: 'error' });
        }
        document.body.removeChild(textarea);
    }

    // Form validation for the create/edit modal -- 2026-09-08 (this
    // session): the same template now renders as either #create-list-form
    // (POST /published-lists/create) or #edit-list-form (POST /published-
    // lists/{id}/update, new this session), so this looks for whichever
    // one is actually on the page instead of a single hardcoded id. The
    // label checkboxes moved onto _widget_list_multiselect.html's own
    // checkbox-dropdown panel (no more #label-checkboxes wrapper) -- that
    // change dropped nothing here, since this never actually gated on the
    // checkboxes' state (see the comment below), only re-ran the same
    // name-only check on every toggle.
    function initCreateFormValidation() {
        var form = document.getElementById('create-list-form') || document.getElementById('edit-list-form');
        if (!form) return;

        var nameInput = document.getElementById('name');
        var submitBtn = document.getElementById('publish-btn') || document.getElementById('save-list-btn');

        function checkValidity() {
            // 2026-09-08 (direct bug report): used to also require at least
            // one label checkbox ticked, but the server has never required
            // that -- create_list()'s `labels` form field defaults to an
            // empty list and _filter_from_form()/evaluate_label_filter()
            // both handle "no labels selected" without error (an unfiltered/
            // empty list is a valid, if not very useful, published list).
            // The stricter client-side gate meant the button silently never
            // enabled itself for a labelless list, even though labels
            // existed in the account -- no error shown anywhere, since this
            // is a disabled-button UI gate, not a validation message. Name
            // is still required (the server's own `name: str = Form(...)`
            // has no default, so an empty name is a real 422, not a UX nicety).
            var hasName = nameInput && nameInput.value.trim().length > 0;
            if (submitBtn) {
                submitBtn.disabled = !hasName;
            }
        }

        if (nameInput) {
            nameInput.addEventListener('input', checkValidity);
        }

        // Initial check
        checkValidity();
    }

    // Truncate long URLs in table with tooltip on hover
    function initUrlTruncation() {
        document.querySelectorAll('.truncated-url').forEach(function (el) {
            var fullUrl = el.getAttribute('data-full-url');
            if (fullUrl && fullUrl.length > 45) {
                el.title = fullUrl;
            }
        });
    }

    // Initialize on DOM ready
    document.addEventListener('DOMContentLoaded', function () {
        initCopyButtons();
        initCreateFormValidation();
        initUrlTruncation();
    });

    // Re-initialize when modal content is swapped (for create modal)
    if (window.CCModal) {
        var originalRefresh = window.CCModal.refresh;
        window.CCModal.refresh = function () {
            return originalRefresh.apply(this, arguments).then(function () {
                initCreateFormValidation();
            });
        };
    }
})();