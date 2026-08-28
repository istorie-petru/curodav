// Label form modal: toggles Project date fields when "Enable Project" is checked,
// and shows a confirm sheet when turning off Space/Project that had real data.
// Loaded globally in base.html so modal.js's wireContent() can init it.

(function () {
    function init(root) {
        const form = root?.querySelector("#label-form");
        if (!form) return;

        const spaceCheckbox = form.querySelector("#generate_space");
        const projectCheckbox = form.querySelector("#is_project");
        const projectFields = form.querySelector(".label-project-fields");
        const advancedSection = form.querySelector("#advanced-section");

        if (!spaceCheckbox || !projectCheckbox || !projectFields) return;

        // Track original state for confirm-on-switch-away
        const originalSpace = spaceCheckbox.checked;
        const originalProject = projectCheckbox.checked;
        let spaceHadChildren = false; // Would be set from server if we had that info
        let projectHadDates = originalProject && (form.querySelector("[name='start_date']")?.value || form.querySelector("[name='end_date']")?.value);

        // Mutual exclusivity: Space and Project can't both be on
        function enforceMutualExclusivity(changedCheckbox) {
            if (changedCheckbox === spaceCheckbox && spaceCheckbox.checked) {
                projectCheckbox.checked = false;
            } else if (changedCheckbox === projectCheckbox && projectCheckbox.checked) {
                spaceCheckbox.checked = false;
            }
            updateProjectFieldsVisibility();
        }

        function updateProjectFieldsVisibility() {
            projectFields.hidden = !projectCheckbox.checked;
        }

        // Confirm before turning off a Space that has children, or a Project with dates
        function checkConfirmOnSwitchAway(changedCheckbox) {
            if (changedCheckbox === spaceCheckbox && originalSpace && !spaceCheckbox.checked && spaceHadChildren) {
                return "This Space has child labels grouped under it. Turning off Space will ungroup them. Continue?";
            }
            if (changedCheckbox === projectCheckbox && originalProject && !projectCheckbox.checked && projectHadDates) {
                return "This Project has a date range set. Turning off Project will clear its dates. Continue?";
            }
            return null;
        }

        [spaceCheckbox, projectCheckbox].forEach((cb) => {
            cb.addEventListener("change", (e) => {
                const confirmMsg = checkConfirmOnSwitchAway(e.target);
                if (confirmMsg) {
                    // Use the existing confirm-sheet mechanism
                    window.ccConfirmSheet({
                        anchor: e.target,
                        message: confirmMsg,
                        onConfirm: () => {
                            enforceMutualExclusivity(e.target);
                        },
                        onCancel: () => {
                            e.target.checked = !e.target.checked; // Revert
                            updateProjectFieldsVisibility();
                        },
                    });
                } else {
                    enforceMutualExclusivity(e.target);
                }
            });
        });

        // Initialize visibility
        updateProjectFieldsVisibility();

        // Optional: auto-open advanced section if Space or Project is already enabled
        if (spaceCheckbox.checked || projectCheckbox.checked) {
            if (advancedSection) advancedSection.open = true;
        }
    }

    // Exported for modal.js wireContent()
    window.CCLabelFormPicker = { init };
})();