(function () {
  if (typeof document === "undefined") {
    return;
  }

  // Plain/bootstrap4 themes always set view-transition-name in CSS and do not
  // use content-visibility toggling, so we only need pre-snapshot scroll sync.
  function isPagingAreaElement(value) {
    return value instanceof Element && value.id === "paging-area";
  }

  document.addEventListener("htmx:beforeTransition", function (event) {
    var detail = event.detail || {};
    if (!isPagingAreaElement(detail.target) && !isPagingAreaElement(detail.elt)) {
      return;
    }

    window.scrollTo(0, 0);
  });
})();
