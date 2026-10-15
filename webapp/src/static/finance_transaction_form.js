// Transaction modal (templates/finance_transaction_modal.html): the Type choice shows or hides the transfer and
// tag fields.
(function () {
  document.addEventListener("change", function (e) {
    const target = e.target;
    if (!target.matches || !target.form || target.form.id !== "finance-transaction-form") return;
    if (target.name === "type") {
      target.form.querySelector(".finance-txn-grid").dataset.txnType = target.value;
    }
  });
})();
