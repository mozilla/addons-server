document.addEventListener('DOMContentLoaded', () => {
  'use strict';

  const checkOrClearAllCheckboxes = (event) => {
    event.target.parentElement
      .querySelectorAll(`input[name="changed_version_ids"]`)
      .forEach(
        (checkbox) =>
          (checkbox.checked = event.target.classList.contains('all-versions')),
      );
    event.preventDefault();
  };

  document
    .querySelectorAll('a.select-versions-all-none')
    .forEach((a) =>
      a.addEventListener('click', checkOrClearAllCheckboxes, true),
    );

  const enableIfChecked = (isChecked, fieldSelector) => {
    const field = document.querySelector(fieldSelector);
    if (isChecked) {
      field.removeAttribute('disabled');
    } else {
      field.setAttribute('disabled', true);
    }
  };

  document
    .querySelector('#id_update_reason_value')
    .addEventListener('click', (e) =>
      enableIfChecked(e.target.checked, '#id_reason'),
    );
  document
    .querySelector('#id_update_reason_value')
    .addEventListener('click', (e) =>
      enableIfChecked(e.target.checked, '#id_canned_reasons'),
    );
  document
    .querySelector('#id_update_url_value')
    .addEventListener('click', (e) =>
      enableIfChecked(e.target.checked, '#id_url'),
    );

  enableIfChecked(
    document.querySelector('#id_update_reason_value').checked,
    '#id_reason',
  );
  enableIfChecked(
    document.querySelector('#id_update_reason_value').checked,
    '#id_canned_reasons',
  );
  enableIfChecked(
    document.querySelector('#id_update_url_value').checked,
    '#id_url',
  );

  document
    .querySelector('#id_canned_reasons')
    .addEventListener('click', (e) => {
      const target = e.target;
      if (target.hasAttribute('text')) {
        document.querySelector('#id_reason').value =
          target.getAttribute('text');
      }
    });
});
