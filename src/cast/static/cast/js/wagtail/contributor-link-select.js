(function () {
  "use strict";

  const selectSelector = "select[data-cast-contributor-link-select]";
  const contributorInputSelector = 'input[type="hidden"][name$="-contributor"]';

  function getRow(element) {
    return element.closest("[data-inline-panel-child]");
  }

  function getContributorInput(select) {
    const row = getRow(select);
    if (!row) {
      return null;
    }
    return row.querySelector(contributorInputSelector);
  }

  function collectOptions(select) {
    if (select.castContributorLinkOptions) {
      return select.castContributorLinkOptions;
    }

    select.castContributorLinkOptions = Array.from(select.options).map((option) => ({
      contributorId: option.dataset.castContributorId || "",
      text: option.textContent,
      value: option.value,
    }));
    return select.castContributorLinkOptions;
  }

  function addOption(select, optionData, selected) {
    const option = new Option(optionData.text, optionData.value, false, selected);
    if (optionData.contributorId) {
      option.dataset.castContributorId = optionData.contributorId;
    }
    select.add(option);
  }

  function syncSelect(select) {
    const options = collectOptions(select);
    const contributorInput = getContributorInput(select);
    const contributorId = contributorInput ? contributorInput.value : "";
    const currentValue = select.value;
    let currentValueStillAllowed = false;

    select.replaceChildren();

    options.forEach((optionData) => {
      const isEmptyOption = !optionData.value;
      const isContributorLink = optionData.contributorId === contributorId;
      if (!isEmptyOption && !isContributorLink) {
        return;
      }

      const selected = optionData.value === currentValue;
      currentValueStillAllowed = currentValueStillAllowed || selected;
      addOption(select, optionData, selected);
    });

    select.disabled = !contributorId;
    if (!currentValueStillAllowed && currentValue) {
      select.value = "";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  function initSelect(select) {
    if (select.dataset.castContributorLinkSelectInitialized === "true") {
      syncSelect(select);
      return;
    }

    select.dataset.castContributorLinkSelectInitialized = "true";
    collectOptions(select);

    const contributorInput = getContributorInput(select);
    if (contributorInput) {
      contributorInput.addEventListener("change", () => syncSelect(select));
    }

    syncSelect(select);
  }

  function initAll(root) {
    root.querySelectorAll(selectSelector).forEach(initSelect);
  }

  document.addEventListener("change", (event) => {
    if (!(event.target instanceof Element) || !event.target.matches(contributorInputSelector)) {
      return;
    }

    const row = getRow(event.target);
    if (row) {
      initAll(row);
    }
  });

  document.addEventListener("w-formset:ready", (event) => initAll(event.target));
  document.addEventListener("w-formset:added", (event) => initAll(event.target));

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => initAll(document));
  } else {
    initAll(document);
  }
})();
