import $ from 'jquery';

// Hijack "Admin / Editor Log in" context menuitem.
$('#admin-login').click(function () {
  window.location = $(this).attr('data-url');
});

$('#fake_fxa_authorization .accounts a').click(function (e) {
  $('#id_email').prop('value', $(this).prop('href').replace('mailto:', ''));
  $('input[name="fake_two_factor_authentication"]').prop('checked', 'true');
  e.preventDefault();
  $('#fake_fxa_authorization').submit();
});
