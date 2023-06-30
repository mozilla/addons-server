document.addEventListener('DOMContentLoaded', () => {
  'use strict';

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
