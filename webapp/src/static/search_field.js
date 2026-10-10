// CCSearchField: the script-built twin of the search_input macro in
// templates/_inputs.html. `wrap(input, iconName)` puts a magnifier (or plus)
// icon and the standard search look around an input a script created.
(function () {
  function wrap(input, iconName) {
    var field = document.createElement("span");
    field.className = "search-field";
    field.innerHTML =
      '<svg class="icon icon-sm" aria-hidden="true"><use href="#icon-' + (iconName || "search") + '"></use></svg>';
    field.appendChild(input);
    return field;
  }
  window.CCSearchField = { wrap: wrap };
})();
