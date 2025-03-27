import $ from 'jquery';
import _ from 'underscore';

import { anonymous } from '../zamboni/init';
// CSRF Tokens
// Hijack the AJAX requests, and insert a CSRF token as a header.

$(document)
  .ajaxSend(function (event, xhr, ajaxSettings) {
    let csrf, $meta;
    // Block anything that starts with 'http:', 'https:', '://' or '//'.
    if (!/^((https?:)|:?[/]{2})/.test(ajaxSettings.url)) {
      // Only send the token to relative URLs i.e. locally.
      $meta = $('meta[name=csrf]');
      if (!anonymous && $meta.length) {
        csrf = $meta.attr('content');
      } else {
        csrf = $("input[name='csrfmiddlewaretoken']").val();
      }
      if (csrf) {
        xhr.setRequestHeader('X-CSRFToken', csrf);
      }
    }
  })
  .ajaxSuccess(function () {
    $(window).trigger('resize'); // Redraw what needs to be redrawn.
  });

export function b64toBlob(data) {
  let b64str = atob(data);
  let counter = b64str.length;
  let u8arr = new Uint8Array(counter);
  while (counter--) {
    u8arr[counter] = b64str.charCodeAt(counter);
  }
  return new Blob([u8arr]);
}
