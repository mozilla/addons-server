document.addEventListener('DOMContentLoaded', () => {
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

  const enableIfChecked = (isChecked, fieldsSelector) => {
    document.querySelectorAll(fieldsSelector).forEach((field) => {
      if (isChecked) {
        field.removeAttribute('disabled');
      } else {
        field.setAttribute('disabled', true);
      }
    });
  };

  const updateReasonValueCheckbox = document.getElementById(
    'id_update_reason_value',
  );
  if (updateReasonValueCheckbox) {
    updateReasonValueCheckbox.addEventListener('click', (e) =>
      enableIfChecked(e.target.checked, '#id_reason'),
    );
    updateReasonValueCheckbox.addEventListener('click', (e) =>
      enableIfChecked(e.target.checked, 'input[name="canned_reasons"]'),
    );
    enableIfChecked(updateReasonValueCheckbox.checked, '#id_reason');
    enableIfChecked(
      updateReasonValueCheckbox.checked,
      'input[name="canned_reasons"]',
    );
  }

  const updateUrlValueCheckbox = document.getElementById('id_update_url_value');
  if (updateUrlValueCheckbox) {
    updateUrlValueCheckbox.addEventListener('click', (e) =>
      enableIfChecked(e.target.checked, '#id_url'),
    );
    enableIfChecked(updateUrlValueCheckbox.checked, '#id_url');
  }

  const fillCannedReason = (e) => {
    const reasonField = document.getElementById('id_reason');
    const cannedReason = e.target.getAttribute('data-block-reason');
    if (e.target.checked) {
      reasonField.setRangeText(
        cannedReason,
        reasonField.selectionStart,
        reasonField.selectionEnd,
        'end',
      );
    } else {
      // Attempt to remove the canned response related to the reason.
      reasonField.value = reasonField.value.replace(cannedReason, '');
    }
  };

  document
    .querySelectorAll('#id_canned_reasons input')
    .forEach((a) => a.addEventListener('click', fillCannedReason));
  // Move the cursor to the end of the textarea
  document.getElementById('id_reason').setSelectionRange(100000, 100000);
});
