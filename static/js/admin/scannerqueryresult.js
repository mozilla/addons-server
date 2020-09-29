document.addEventListener('DOMContentLoaded', () => {
  let result_list = document.querySelector(
    'body.change-list.model-scannerqueryresult #result_list',
  );

  if (!result_list) {
    // This is only for the scanners query result change list page.
    return;
  }

  let current_addon = {
    cell: null,
    link: null,
  };

  for (row of result_list.tBodies[0].rows) {
    let new_addon = {
      cell: row.querySelector('.field-formatted_addon'),
      link: row.querySelector('.field-formatted_addon a'),
    };

    // FIXME: for performance, it might be better to store the elements we
    // want to change in a list and change them in one go outside of this
    // loop ?
    if (new_addon.link) {
      let classNames = [];

      if (
        current_addon.cell &&
        current_addon.link &&
        new_addon.link.text == current_addon.link.text
      ) {
        // That new row contains the same add-on as the previous one.
        classNames.push('same-addon');
        if (new_addon.link.href == current_addon.link.href) {
          // If it's the same link as before, we remove the cell and
          // increment the rowspwan of the first cell of the row we
          // found for that add-on.
          current_addon.cell.rowSpan++;
          new_addon.cell.parentElement.removeChild(new_addon.cell);
        } else {
          // If it's not the same link, then we have just changed
          // channels for the same add-on. We don't do anything to
          // the cell, but add a classname to differentiate.
          classNames.push('different-channel');
          // The "new_addon" need to be updated so that we
          // "start" the row from there.
          current_addon = {
            cell: new_addon.cell,
            link: new_addon.link,
          };
        }
      } else {
        // New add-on, we add a different class to the row and store
        // this add-on as the current one.
        classNames.push('different-addon');
        current_addon = {
          cell: new_addon.cell,
          link: new_addon.link,
        };
      }
      // Add the className(s) now that we're done determining what we
      // need.
      if (classNames) {
        row.classList.add(...classNames);
      }
    }
  }
});
