// CSRF Tokens
// Hijack the AJAX requests, and insert a CSRF token as a header.

$(document)
  .ajaxSend(function (event, xhr, ajaxSettings) {
    var csrf, $meta;
    // Block anything that starts with 'http:', 'https:', '://' or '//'.
    if (!/^((https?:)|:?[/]{2})/.test(ajaxSettings.url)) {
      // Only send the token to relative URLs i.e. locally.
      $meta = $('meta[name=csrf]');
      if (!z.anonymous && $meta.length) {
        csrf = $meta.attr('content');
      } else {
        csrf = $("input[name='csrfmiddlewaretoken']").val();
      }
      if (csrf) {
        xhr.setRequestHeader('X-CSRFToken', csrf);
      }
    }
  })
  .ajaxSuccess(function (event, xhr, ajaxSettings) {
    $(window).trigger('resize'); // Redraw what needs to be redrawn.
  });

function b64toBlob(data) {
  var b64str = atob(data);
  var counter = b64str.length;
  var u8arr = new Uint8Array(counter);
  while (counter--) {
    u8arr[counter] = b64str.charCodeAt(counter);
  }
  return new Blob([u8arr]);
}
