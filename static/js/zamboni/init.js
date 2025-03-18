import $ from 'jquery';

// Manually set jQuery on the window to ensure
// It's avialable globally for any dependent modules.
window.jQuery = $;
window.$ = $;

$(document).ready(function () {
  if (readonly) {
    $('form[method=post]')
      .before(
        gettext(
          'This feature is temporarily disabled while we perform website maintenance. Please check back a little later.',
        ),
      )
      .find('input, button, select')
      .prop('disabled', true)
      .addClass('disabled');
  }
});

export function escape_(s) {
  if (s === undefined) {
    return;
  }
  return s
    .replace(/&/g, '&amp;')
    .replace(/>/g, '&gt;')
    .replace(/</g, '&lt;')
    .replace(/'/g, '&#39;')
    .replace(/"/g, '&#34;');
}

/* Details for the current application. */
export const anonymous = JSON.parse(
  document.body.getAttribute('data-anonymous'),
);
const readonly = JSON.parse(document.body.getAttribute('data-readonly'));
