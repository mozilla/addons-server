document.addEventListener('DOMContentLoaded', () => {
  'use strict';

  const promotedAddonForm = document.getElementById('promotedaddon_form');

  if (!promotedAddonForm) {
    return;
  }

  const groupSelect = promotedAddonForm.querySelector('#id_group_id');
  let initialIndex = groupSelect.selectedIndex;
  const initialGroup = groupSelect.options[initialIndex].label || '';

  // Enable the listener only when loading a promoted add-on belonging to a
  // group that requires a subscription.
  if (['sponsored', 'verified'].includes(initialGroup.toLowerCase())) {
    groupSelect.addEventListener('change', () => {
      if (
        !confirm(
          "This promoted add-on belongs to a group that requires a Stripe subscription, which should be cancelled in Stripe first. If you confirm this action, you will be able to update the group but Stripe won't be notified and the Stripe subscription will remain active. Do you really want to continue?",
        )
      ) {
        groupSelect.selectedIndex = initialIndex;
      }
    });
  }
});
