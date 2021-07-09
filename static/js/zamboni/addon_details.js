/** Addons Display page */

/* general initialization */
$(document).ready(function () {
  if ($('#addon.primary').length == 0) return;

  var lb_baseurl = z.static_url + 'img/jquery-lightbox/';  // FIXME: all of this would break. Ideally it would be in a CSS that would get rewritten, or passed from HTML through a bunch of data attributes
  $("a[rel='jquery-lightbox']").lightBox({
    overlayOpacity: 0.6,
    imageBlank: lb_baseurl + 'lightbox-blank.gif',
    imageLoading: lb_baseurl + 'lightbox-ico-loading.gif',
    imageBtnClose: lb_baseurl + 'close.png',
    imageBtnPrev: lb_baseurl + 'goleft.png',
    imageBtnNext: lb_baseurl + 'goright.png',
    containerResizeSpeed: 350,
  });

  var etiquette_box = $('#addons-display-review-etiquette').hide();
  $('#short-review').focus(function () {
    etiquette_box.show('fast');
  });
});
