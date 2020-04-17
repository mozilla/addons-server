// The name of the default rule used for some default values in the form.
const DEFAULT_RULE_NAME = 'your_rule_name';

const selectedScannerIsYara = (select) => {
  return select.options[select.selectedIndex].label === 'yara';
};

const selectedScannerIsNone = (select) => {
  return select.options[select.selectedIndex].value === '';
};

// This function changes the visibility of the `definition` field depending on
// the scanner that has been selected. Only "yara" rules have definitions for
// now, so it is restricted to that. It also sets a default value when there is
// no value yet and the scanner is "yara".
const showOrHideDefinition = (select) => {
  const definition = document.querySelector('.field-definition');
  const isYara = selectedScannerIsYara(select);

  definition.style.display = isYara ? 'block' : 'none';

  if (isYara) {
    const textarea = definition.querySelector('#id_definition');

    if (textarea.value.trim().length === 0) {
      textarea.value = `rule ${DEFAULT_RULE_NAME}
{
  // This is a stub definition that will never match.
  // See: https://yara.readthedocs.io/en/latest/
  condition: false
  // The following special variables are always available:
  // is_json_file (true for filenames ending with .json)
  // is_manifest_file (true for manifest.json file at the root)
  // is_locale_file (true for messages.json files in _locales/ folder at the root)
}`;
    }
  }
}

// This function changes the visibility of the `name` field in the "change
// form". We only want to show this field when a scanner is selected and this
// scanner is not "yara" (because we will infer the name of the rule using the
// Yara definition). It also sets a default value when there is no value yet
// and the scanner is "yara".
const showOrHideName = (select) => {
  const name = document.querySelector('.field-name');
  const isNone = selectedScannerIsNone(select);
  const isYara = selectedScannerIsYara(select);

  name.style.display = (isNone || isYara) ? 'none' : 'block';

  if (isYara) {
    const nameInput = document.querySelector('#id_name');

    if (nameInput.value.trim().length === 0) {
      nameInput.value = DEFAULT_RULE_NAME;
    }
  }
}

const scannerSelect = document.querySelector('#id_scanner');
const definitionTextarea = document.querySelector('#id_definition');

// We listen to `scanner` changes to update the visibility of some fields in
// the form. For instance, when the "yara" scanner is selected, we want to show
// the `definition` field and hide the `name` field.
scannerSelect.addEventListener('change', (event) => {
  const select = event.target;

  showOrHideDefinition(select);
  showOrHideName(select);
});

// Update name field value on definition change. This is needed because the
// field is hidden. We parse the name of the rule and, if successful, we update
// the value of the name.
definitionTextarea.addEventListener('input', (event) => {
  const { value } = event.target;

  const nameInput = document.querySelector('#id_name');
  // This pattern matches strings like `rule some_rule_name {`.
  const matches = value.match(/rule\s+(.+?)\s+{/);

  if (matches.length === 2) {
    // The name of the rule is validated by the django app anyway so we only
    // need to pass the "raw" rule name to the input.
    nameInput.value = matches[1];
  }
});

// It is likely that these two fields will be hidden by default because the
// form does not have a pre-selected value for the `scanner` select.
showOrHideName(scannerSelect);
showOrHideDefinition(scannerSelect);
