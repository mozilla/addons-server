// Hijack "Admin / Editor Log in" context menuitem.
$('#admin-login').click(function () {
  window.location = $(this).attr('data-url');
});

$('#fake_fxa_authorization .accounts a').click(function (e) {
  $('#id_email').prop('value', $(this).prop('href').replace('mailto:', ''));
  e.preventDefault();
  $('#fake_fxa_authorization').submit();
});
