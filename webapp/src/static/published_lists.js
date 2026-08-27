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

    // Form validation for create modal
    function initCreateFormValidation() {
        var form = document.getElementById('create-list-form');
        if (!form) return;

        var nameInput = document.getElementById('name');
        var checkboxes = document.querySelectorAll('#label-checkboxes input[type="checkbox"]');
        var submitBtn = document.getElementById('publish-btn');

        function checkValidity() {
            var hasName = nameInput && nameInput.value.trim().length > 0;
            var hasLabel = Array.from(checkboxes).some(function (cb) { return cb.checked; });
            if (submitBtn) {
                submitBtn.disabled = !(hasName && hasLabel);
            }
        }

        if (nameInput) {
            nameInput.addEventListener('input', checkValidity);
        }
        checkboxes.forEach(function (cb) {
            cb.addEventListener('change', checkValidity);
        });

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