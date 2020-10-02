document.addEventListener('DOMContentLoaded', () => {
  'use strict';

  const result_list = document.querySelector(
    'body.change-list.model-scannerqueryresult #result_list',
  );

  if (!result_list) {
    // This is only for the scanners query result change list page.
    return;
  }

  let current_addon = {
    name_cell: null,
    guid_cell: null,
    channel_cell: null,
  };

  for (const row of result_list.tBodies[0].rows) {
    let new_addon = {
      name_cell: row.querySelector('.field-addon_name'),
      guid_cell: row.querySelector('.field-guid'),
      channel_cell: row.querySelector('.field-formatted_channel'),
    };

    // FIXME: for performance, it might be better to store the elements we
    // want to change in a list and change them in one go outside of this
    // loop ?
    if (new_addon.guid_cell && new_addon.name_cell && new_addon.channel_cell) {
      let classNames = [];

      if (
        current_addon.name_cell &&
        current_addon.guid_cell &&
        new_addon.guid_cell.textContent == current_addon.guid_cell.textContent
      ) {
        // That new row contains the same add-on as the previous one. Mark it
        // as such, remove the new guid & name cell as they are duplicates.
        classNames.push('same-addon');
        current_addon.guid_cell.rowSpan++;
        row.removeChild(new_addon.guid_cell);
        current_addon.name_cell.rowSpan++;
        row.removeChild(new_addon.name_cell);

        if (
          new_addon.channel_cell.textContent !=
          current_addon.channel_cell.textContent
        ) {
          // Still the same add-on, but different channel. We don't do
          // anything to the cell, but add a classname to the row to
          // differentiate it.
          classNames.push('different-channel');
          current_addon.channel_cell = new_addon.channel_cell;
        }
      } else {
        // New add-on, we add a different class to the row and store
        // this add-on as the current one.
        classNames.push('different-addon');
        current_addon = new_addon;
      }
      // Add the className(s) now that we're done determining what we
      // need.
      if (classNames) {
        row.classList.add(...classNames);
      }
    }
  }
});
