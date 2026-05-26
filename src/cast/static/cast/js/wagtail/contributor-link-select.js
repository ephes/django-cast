(function () {
  "use strict";

  const selectSelector = "select[data-cast-contributor-link-select]";
  const contributorInputSelector = 'input[type="hidden"][name$="-contributor"]';
  const roleSelectSelector = 'select[name$="-role"]';
  const rowIdInputSelector = 'input[type="hidden"][name$="-id"]';

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

  function getRoleSelect(select) {
    const row = getRow(select);
    if (!row) {
      return null;
    }
    return row.querySelector(roleSelectSelector);
  }

  function getRowIdInput(select) {
    const row = getRow(select);
    if (!row) {
      return null;
    }
    return row.querySelector(rowIdInputSelector);
  }

  function getContributorId(select) {
    const contributorInput = getContributorInput(select);
    return contributorInput ? contributorInput.value : "";
  }

  function isUnsavedRow(select) {
    const rowIdInput = getRowIdInput(select);
    return Boolean(rowIdInput && !rowIdInput.value);
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

  function collectContributorDefaults(select) {
    if (!select.castContributorDefaults) {
      select.castContributorDefaults = {};
    }
    return select.castContributorDefaults;
  }

  function mergeContributorDefaults(select, contributorId, data) {
    if (!contributorId || !data) {
      return;
    }

    const defaults = collectContributorDefaults(select);
    const contributorDefaults = defaults[contributorId] || {};
    if (Object.prototype.hasOwnProperty.call(data, "defaultLinkId")) {
      contributorDefaults.defaultLinkId = String(data.defaultLinkId || "");
    }
    if (Object.prototype.hasOwnProperty.call(data, "defaultRole")) {
      contributorDefaults.defaultRole = String(data.defaultRole || "");
    }
    defaults[contributorId] = contributorDefaults;
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
        mergeContributorDefaults(select, contributorId, data);
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

  function dispatchChange(element) {
    element.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function setRoleSelectDefault(roleSelect, value) {
    roleSelect.dataset.castContributorRoleDefaulting = "true";
    roleSelect.value = value;
    dispatchChange(roleSelect);
    delete roleSelect.dataset.castContributorRoleDefaulting;
  }

  function getContributorDefaultLinkId(select, contributorId) {
    const defaults = collectContributorDefaults(select)[contributorId];
    if (defaults && Object.prototype.hasOwnProperty.call(defaults, "defaultLinkId")) {
      return defaults.defaultLinkId;
    }
    if (getContributorOptionsUrl(select, contributorId)) {
      return "";
    }

    const firstContributorOption = collectOptions(select).find(
      (optionData) => optionData.value && optionData.contributorId === contributorId,
    );
    return firstContributorOption ? firstContributorOption.value : "";
  }

  function applyContributorDefaults(select, contributorId) {
    if (!contributorId) {
      return;
    }

    const defaults = collectContributorDefaults(select)[contributorId] || {};
    const roleSelect = getRoleSelect(select);
    if (
      roleSelect &&
      defaults.defaultRole &&
      roleSelect.dataset.castContributorRoleTouched !== "true" &&
      roleSelect.value !== defaults.defaultRole
    ) {
      setRoleSelectDefault(roleSelect, defaults.defaultRole);
    }

    const defaultLinkId = getContributorDefaultLinkId(select, contributorId);
    if (
      !select.value &&
      defaultLinkId &&
      Array.from(select.options).some((option) => option.value === defaultLinkId)
    ) {
      select.value = defaultLinkId;
      dispatchChange(select);
    }
  }

  function syncSelectWithFreshOptions(select, applyDefaults) {
    const contributorId = getContributorId(select);
    syncSelect(select);
    if (applyDefaults) {
      applyContributorDefaults(select, contributorId);
    }

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
      if (applyDefaults) {
        applyContributorDefaults(select, contributorId);
      }
    });
  }

  function resetRoleTouched(select) {
    const roleSelect = getRoleSelect(select);
    if (roleSelect) {
      delete roleSelect.dataset.castContributorRoleTouched;
    }
  }

  function handleContributorChange(select) {
    resetRoleTouched(select);
    syncSelectWithFreshOptions(select, true);
  }

  function initSelect(select) {
    if (select.dataset.castContributorLinkSelectInitialized === "true") {
      syncSelectWithFreshOptions(select, false);
      return;
    }

    select.dataset.castContributorLinkSelectInitialized = "true";
    collectOptions(select);

    const contributorInput = getContributorInput(select);
    if (contributorInput) {
      contributorInput.addEventListener("change", () => handleContributorChange(select));
    }

    const roleSelect = getRoleSelect(select);
    if (roleSelect) {
      roleSelect.addEventListener("change", () => {
        if (roleSelect.dataset.castContributorRoleDefaulting === "true") {
          return;
        }
        roleSelect.dataset.castContributorRoleTouched = "true";
      });
    }

    syncSelect(select);
    if (isUnsavedRow(select) && getContributorId(select)) {
      syncSelectWithFreshOptions(select, true);
    }
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
