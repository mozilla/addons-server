django.jQuery(document).ready(function ($) {
  'use strict';

  // Recalculate Hash
  $('.recalc').click(function (e) {
    var $this = $(this),
      csrf = $("input[name='csrfmiddlewaretoken']").val();
    e.preventDefault();

    $.ajax($this.attr('href'), {
      headers: { 'X-CSRFToken': csrf },
      dataType: 'json',
      method: 'POST',
      beforeSend: function () {
        $this.html('Recalcing&hellip;');
      },
      success: function () {
        $this.text('Done!');
      },
      error: function () {
        $this.text('Error :(');
      },
      complete: function () {
        setTimeout(function () {
          $this.text('Recalc Hash');
        }, 2000);
      },
    });
  });
});
