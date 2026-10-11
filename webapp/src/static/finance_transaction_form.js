// Transaction modal (templates/finance_transaction_modal.html): the Type choice shows or hides the transfer and
// label fields, and the chosen label decides which tags are offered.
(function () {
  document.addEventListener("change", async function (e) {
    const target = e.target;
    if (!target.matches || !target.form || target.form.id !== "finance-transaction-form") return;
    if (target.name === "status") {
      target.form.querySelector(".finance-txn-grid").dataset.status = target.value;
    } else if (target.name === "type") {
      target.form.querySelector(".finance-txn-grid").dataset.txnType = target.value;
    } else if (target.name === "label") {
      const slot = document.getElementById("finance-tag-field");
      const picked = [...document.querySelectorAll('input[name="tags"]:checked')]
        .map((el) => "&tags=" + encodeURIComponent(el.value)).join("");
      const res = await fetch(target.form.dataset.tagUrl + "?label=" + encodeURIComponent(target.value) + picked);
      if (slot && res.ok) slot.innerHTML = await res.text();
    }
  });
})();
