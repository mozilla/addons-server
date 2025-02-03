import $ from 'jquery';

/* jQuery Zoombox: https://github.com/technicolorenvy/jquery-zoombox */
$.fn.zoomBox = function (opts) {
  let box, boxX, boxY, boxW, boxH;
  let img, imgW, imgH;

  opts = $.extend(
    {
      interval: 400,
      sensitivity: 100000,
      zoomSpeed: 200,
      zoomMargin: 10,
    },
    opts || {},
  );

  this.each(function () {
    initMetrics(this);
    $(img).css(imageCenter());
  });

  return this.hoverIntent(
    $.extend(
      {
        over: onMouseEnter,
        out: onMouseLeave,
      },
      opts,
    ),
  );

  function initMetrics(elem) {
    let jimg = $('img', elem);
    jimg.data('origWidth', jimg.attr('width'));
    jimg.data('origHeight', jimg.attr('height'));
    updateMetrics(elem);
  }

  function updateMetrics(elem) {
    let jbox = $(elem);
    let jimg = $('img', elem);

    box = elem;
    boxX = jbox.offset().left;
    boxY = jbox.offset().top;
    boxW = jbox.width();
    boxH = jbox.height();

    img = jimg.get(0);
    imgW = jimg.data('origWidth');
    imgH = jimg.data('origHeight');
  }

  function onMouseEnter(e) {
    updateMetrics(e.currentTarget);

    $(img).stop(false, true);

    $(img).animate(
      imageZoom(e.pageX, e.pageY),
      opts.zoomSpeed,
      'linear',
      function () {
        $(box).on('mousemove', onMouseMove);
      },
    );
  }

  function onMouseMove(e) {
    $(img).css(imageZoom(e.pageX, e.pageY));
  }

  function onMouseLeave(e) {
    $(img).stop(false, true);
    $(box).off('mousemove', onMouseMove);
    $(img).animate(imageCenter(), opts.zoomSpeed, 'linear');
    box = img = null;
  }

  function imageCenter() {
    let sx = (boxW - 2 * opts.zoomMargin) / imgW;
    let sy = (boxH - 2 * opts.zoomMargin) / imgH;
    let scale = Math.min(sx, sy);

    return {
      /* line below patched to always pin images to the top right -
      helps when images don't fill the div width for static themes.*/
      left: boxW - scale * imgW - opts.zoomMargin,
      top: (boxH - scale * imgH) / 2,
      width: scale * imgW,
      height: scale * imgH,
    };
  }

  function imageZoom(x, y) {
    x = x - boxX;
    y = y - boxY;

    let sx = boxW / imgW;
    let sy = boxH / imgH;

    let x2 = boxW / 2 - (x * imgW) / boxW;
    let y2 = boxH / 2 - (y * imgH) / boxH;

    x2 = Math.max(Math.min(x2, 0), boxW - imgW);
    y2 = Math.max(Math.min(y2, 0), boxH - imgH);

    return {
      left: x2,
      top: y2,
      width: imgW,
      height: imgH,
    };
  }
};
