const selectedScannerIsYara = (select) => {
  return select.options[select.selectedIndex].label === 'yara';
};

const showOrHideDefinition = (select) => {
  const definition = document.querySelector('.field-definition');
  const isYara = selectedScannerIsYara(select);

  definition.style.display = isYara ? 'block' : 'none';

  if (isYara) {
    const name = document.querySelector('#id_name').value.trim();
    const textarea = definition.querySelector('#id_definition');

    if (name.length && textarea.value.trim().length === 0) {
      textarea.value = `rule ${name}
{
  // This is a stub definition that will never match.
  // See: https://yara.readthedocs.io/en/latest/
  condition: false
}`;
    }
  }
}

const scannerSelect = document.querySelector('#id_scanner');

// Update definition field "visibility" on scanner change.
scannerSelect.addEventListener('change', (event) => {
  const select = event.target;
  showOrHideDefinition(select);
});

// Likely hide the definition field by default.
showOrHideDefinition(scannerSelect);
