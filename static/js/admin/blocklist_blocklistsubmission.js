document.addEventListener('DOMContentLoaded', () => {
  'use strict';

  const checkAllCheckboxes = (event) =>
    event.target.parentElement
      .querySelectorAll(`input[name="changed_version_ids"]`)
      .forEach((checkbox) => checkbox.setAttribute('checked', true));
  const clearAllCheckboxes = (event) =>
    event.target.parentElement
      .querySelectorAll(`input[name="changed_version_ids"]`)
      .forEach((checkbox) => checkbox.removeAttribute('checked'));
  document
    .querySelectorAll('a.select-all-versions')
    .forEach((a) => a.addEventListener('click', checkAllCheckboxes, true));
  document
    .querySelectorAll('a.select-none-versions')
    .forEach((a) => a.addEventListener('click', clearAllCheckboxes, true));
});
