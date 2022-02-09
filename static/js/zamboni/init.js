/* Global initialization script */
var z = {};

$(document).ready(function () {
  if (z.readonly) {
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

/* prevent-default function wrapper */
function _pd(func) {
  return function (e) {
    e.preventDefault();
    func.apply(this, arguments);
  };
}

var escape_ = function (s) {
  if (s === undefined) {
    return;
  }
  return s
    .replace(/&/g, '&amp;')
    .replace(/>/g, '&gt;')
    .replace(/</g, '&lt;')
    .replace(/'/g, '&#39;')
    .replace(/"/g, '&#34;');
};

/* Details for the current application. */
z.anonymous = JSON.parse(document.body.getAttribute('data-anonymous'));
z.readonly = JSON.parse(document.body.getAttribute('data-readonly'));
