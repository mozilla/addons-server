$(document).ready(function () {
  var KEY_TIMEOUT = 30000;

  function hideSecret() {
    $('#jwtsecret').val('').hide();
    $('#show-key').show();
  }

  function showSecret() {
    console.log('showSecret');
    $.getJSON(
      $('#api-credentials').data('key-url'),
      {
        'key': $('#jwtkey').val(),
        'csrfmiddlewaretoken': $("input[name='csrfmiddlewaretoken']",
                                 $form).val(),
      },
      function (data) {
        $('#jwtsecret').val(data.secret).show();
        $('#show-key').hide();

        window.setTimeout(clearKey, KEY_TIMEOUT);
      }
    );
  }

  $('#show-key').click(function (event) {
    console.log('asdgasdg');

    showSecret();
  });
});
