// Hijack "Admin / Editor Log in" context menuitem.
$('#admin-login').click(function () {
  window.location = $(this).attr('data-url');
});

// Recaptcha
var RecaptchaOptions = { theme: 'custom' };

$('#recaptcha_different').click(function (e) {
  e.preventDefault();
  Recaptcha.reload();
});

$('#recaptcha_audio').click(function (e) {
  e.preventDefault();
  var toggleType = this.getAttribute('data-nextType') || 'audio';
  Recaptcha.switch_type(toggleType);
  this.setAttribute(
    'data-nextType',
    toggleType === 'audio' ? 'image' : 'audio',
  );
});

$('#recaptcha_help').click(function (e) {
  e.preventDefault();
  Recaptcha.showhelp();
});
