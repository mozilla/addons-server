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

  const enableIfChecked = (isChecked, fieldId) => {
    const field = document.querySelector(`#${fieldId}`);
    if (isChecked) {
      field.removeAttribute('disabled');
    } else {
      field.setAttribute('disabled', true);
    }
  };

  document
    .querySelector('#id_update_reason')
    .addEventListener('click', (e) =>
      enableIfChecked(e.target.checked, 'id_reason'),
    );

  document
    .querySelector('#id_update_url')
    .addEventListener('click', (e) =>
      enableIfChecked(e.target.checked, 'id_url'),
    );

  enableIfChecked(
    document.querySelector('#id_update_reason').checked,
    'id_reason',
  );
  enableIfChecked(document.querySelector('#id_update_url').checked, 'id_url');
});
