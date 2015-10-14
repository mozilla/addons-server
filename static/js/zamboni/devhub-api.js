$(document).ready(function () {
  var KEY_TIMEOUT = 30000;

  function clearKey() {
    $('#jwtkey').val('');
    $('#jwtsecret').val('');
  }

  function regenKey() {
    $.getJSON(
      $('#api-credentials').data('key-url'),
      function (data) {
        $('#jwtkey').val(data.key);
        $('#jwtsecret').val(data.secret);

        window.setTimeout(clearKey, KEY_TIMEOUT);
      }
    );
  }

  $('#show-key').click(function (event) {
    regenKey();
  });

  window.setTimeout(clearKey, KEY_TIMEOUT);
});
