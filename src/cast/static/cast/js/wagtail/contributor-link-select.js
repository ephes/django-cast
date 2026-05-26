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

  function getContributorId(select) {
    const contributorInput = getContributorInput(select);
    return contributorInput ? contributorInput.value : "";
  }

  function collectOptions(select) {
    if (select.castContributorLinkOptions) {
      return select.castContributorLinkOptions;
    }

    select.castContributorLinkOptions = Array.from(select.options).map((option) => ({
      contributorId: option.dataset.castContributorId || "",
      text: option.textContent || "",
      value: option.value,
    }));
    return select.castContributorLinkOptions;
  }

  function mergeOptions(select, optionList) {
    const options = collectOptions(select);
    const knownValues = new Set(options.map((option) => option.value));

    optionList.forEach((optionData) => {
      const value = String(optionData.value || "");
      if (!value || knownValues.has(value)) {
        return;
      }

      options.push({
        contributorId: String(optionData.contributorId || ""),
        text: String(optionData.text || ""),
        value,
      });
      knownValues.add(value);
    });
  }

  function getContributorOptionsUrl(select, contributorId) {
    const url = select.dataset.castContributorLinkOptionsUrl;
    if (!url || !contributorId) {
      return null;
    }

    const optionsUrl = new URL(url, window.location.href);
    optionsUrl.searchParams.set("contributor_id", contributorId);
    return optionsUrl.toString();
  }

  function loadContributorOptions(select, contributorId) {
    const url = getContributorOptionsUrl(select, contributorId);
    if (!url) {
      return null;
    }

    if (!select.castContributorLinkOptionRequests) {
      select.castContributorLinkOptionRequests = {};
    }
    if (select.castContributorLinkOptionRequests[contributorId]) {
      return select.castContributorLinkOptionRequests[contributorId];
    }

    const request = fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Could not load contributor links: ${response.status}`);
        }
        return response.json();
      })
      .then((data) => {
        if (Array.isArray(data.links)) {
          mergeOptions(select, data.links);
        }
      })
      .catch(() => {
        delete select.castContributorLinkOptionRequests[contributorId];
      });

    select.castContributorLinkOptionRequests[contributorId] = request;
    return request;
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
    const contributorId = getContributorId(select);
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

    select.disabled = !contributorId || select.dataset.castContributorLinkSelectLoading === contributorId;
    if (!currentValueStillAllowed && currentValue) {
      select.value = "";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  function syncSelectWithFreshOptions(select) {
    const contributorId = getContributorId(select);
    syncSelect(select);

    const request = loadContributorOptions(select, contributorId);
    if (!request) {
      return;
    }

    select.dataset.castContributorLinkSelectLoading = contributorId;
    syncSelect(select);
    request.then(() => {
      if (getContributorId(select) !== contributorId) {
        return;
      }
      delete select.dataset.castContributorLinkSelectLoading;
      syncSelect(select);
    });
  }

  function initSelect(select) {
    if (select.dataset.castContributorLinkSelectInitialized === "true") {
      syncSelectWithFreshOptions(select);
      return;
    }

    select.dataset.castContributorLinkSelectInitialized = "true";
    collectOptions(select);

    const contributorInput = getContributorInput(select);
    if (contributorInput) {
      contributorInput.addEventListener("change", () => syncSelectWithFreshOptions(select));
    }

    syncSelect(select);
  }

  function initAll(root) {
    root.querySelectorAll(selectSelector).forEach(initSelect);
  }

  document.addEventListener("w-formset:ready", (event) => initAll(event.target));
  document.addEventListener("w-formset:added", (event) => initAll(event.target));

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => initAll(document));
  } else {
    initAll(document);
  }
})();
