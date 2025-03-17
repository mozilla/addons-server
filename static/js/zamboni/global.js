import $ from 'jquery';
import _ from 'underscore';
import { format } from '../lib/format';
import { unicode_letters } from './unicode';
// Things global to the site should go here, such as re-usable helper
// functions and common ui components.

// Tooltip display. If you give an element a class of 'tooltip', it will
// display a tooltip on hover. The contents of the tip will be the element's
// title attribute OR the first title attribute in its children. Titles are
// swapped out by the code so the native title doesn't display. If the title of
// the element is changed while the tooltip is displayed, you can update the
// tooltip by with the following:
//      $el.trigger("tooltip_change");
//
// You can add a title by using the following format for the title attribute:
//      <div title="Title here :: Rest goes after the two colons"></div>
//
// You can set a custom timeout (milliseconds) by using data-delay:
//      <div data-delay="100" title="hi"></div>

let uid = 0;

$.fn.tooltip = function (tip_el) {
  let $tip = $(tip_el),
    $msg = $('span', $tip),
    $targets = this,
    timeout = false,
    $tgt,
    $title,
    delay;

  function setTip() {
    if (!$tgt) return;
    let pos = $tgt.offset(),
      title = $title.attr('title'),
      html = $title.attr('data-tooltip-html');

    delay = $title.is('[data-delay]') ? $title.attr('data-delay') : 300;

    if (!html && title.indexOf('::') > 0) {
      let title_split = title.split('::');
      $msg.text('');
      $msg.append($('<strong>', { text: title_split[0].trim() }));
      $msg.append($('<span>', { text: title_split[1].trim() }));
    } else {
      $msg[html ? 'html' : 'text'](title);
    }

    $title.attr('data-oldtitle', title).attr('title', '');

    let tw = $tip.outerWidth(false) / 2,
      th = $tip.outerHeight(false),
      toX = pos.left + $tgt.innerWidth() / 2 - tw - 1,
      toY = pos.top - $tgt.innerHeight() - th - 2;

    timeout = setTimeout(function () {
      $tip
        .css({
          left: toX + 'px',
          top: toY + 'px',
        })
        .show();
    }, delay);
  }

  $(document.body).on('tooltip_change', setTip);

  function mouseover() {
    $tgt = $(this);
    if ($tgt.hasClass('formerror')) $tip.addClass('error');
    $title = $tgt.attr('title') ? $tgt : $('[title]', $tgt).first();
    if ($title.length) {
      setTip();
    }
  }

  function mouseout() {
    clearTimeout(timeout);
    $tip.hide().removeClass('error');
    if ($title && $title.length) {
      $tgt = $(this);
      $title
        .attr('title', $title.attr('data-oldtitle'))
        .attr('data-oldtitle', '');
    }
  }

  $targets.on('mouseover', mouseover).on('mouseout', mouseout);
};

// Setting up site tooltips.
$(document).ready(function () {
  $('.tooltip').tooltip('#tooltip');
});

// returns an event handler that will hide/unbind an element when a click is
// registered outside itself.
function makeBlurHideCallback(el) {
  const hider = function (e) {
    const _root = el.get(0);
    // Bail if the click was somewhere on the popup.
    if (e) {
      if (
        (e.type == 'click' && _root == e.target) ||
        _.indexOf($(e.target).parents(), _root) != -1
      ) {
        return;
      }
    }
    el.hideMe();
    if (el.o.emptyme) {
      el.empty();
    }
    if (el.o.deleteme) {
      el.remove();
    }
  };
  return hider;
}

// makes an element into a popup.
// click_target defines the element/elements that trigger the popup.
// currently presumes the given element uses the '.popup' style
// o takes the following optional fields:
//     callback:    a function to run before displaying the popup. Returning
//                  false from the function cancels the popup.
//     container:   if set the popup will be appended to the container before
//                  being displayed.
//     pointTo:     if set, the popup will be appended to document.body and
//                  absolutely positioned to point at the given element
//     width:       the width of the popup.
//     delegate:    delegates the click handling of the click_target to the
//                  specified parent element.
//     hideme:      defaults to true; if set to false, popup will not be hidden
//                  when the user clicks outside of it.
//     emptyme:     defaults to false; if set to true, popup will be cleared
//                  after it is hidden.
// note: all options may be overridden and modified by returning them in an
//       object from the callback.
$.fn.popup = function (click_target, o) {
  o = o || {};

  let $ct = $(click_target),
    $popup = this,
    spawned = 0;

  $popup.o = $.extend(
    {
      delegate: false,
      callback: false,
      container: false,
      hideme: true,
      emptyme: false,
      pointTo: false,
      offset: {},
      width: 300,
    },
    o,
  );

  $popup.setWidth = function (w) {
    $popup.css({ width: w });
    return $popup;
  };

  $popup.setPos = function (el, offset) {
    offset = offset || $popup.o.offset;
    el = el || $popup.o.pointTo;
    if (!el) return false;
    $popup.detach().appendTo('body');
    let pt = $(el),
      pos = pt.offset(),
      tw = pt.outerWidth(false) / 2,
      th = pt.outerHeight(false),
      pm = pos.left + tw > $('body').outerWidth(false) / 2,
      os = pm ? $popup.outerWidth(false) - 84 : 63,
      toX = pos.left + (offset.x || tw) - os,
      toY = pos.top + (offset.y || th) + 4;
    $popup.removeClass('left');
    if (pm) $popup.addClass('left');
    $popup.css({
      left: toX,
      top: toY,
      right: 'inherit',
      bottom: 'inherit',
    });
    $popup.o.pointTo = el;
    return $popup;
  };

  $popup.hideMe = function () {
    $popup.hide();
    $popup.off();
    $(document.body).off('click.' + uid++, $popup.hider);
    return $popup;
  };

  function handler(e) {
    e.preventDefault();
    spawned = e.timeStamp;
    let resp = o.callback
      ? o.callback.call($popup, {
          click_target: this,
          evt: e,
        })
      : true;
    $popup.o = $.extend({ click_target: this }, $popup.o, resp);
    if (resp) {
      $popup.render();
    }
  }

  $popup.render = function () {
    let p = $popup.o,
      hideCallback = makeBlurHideCallback($popup);
    $popup.hider = function (e) {
      if (e.timeStamp != spawned) {
        hideCallback.call(this, e);
      }
    };
    if (p.hideme) {
      setTimeout(function () {
        $(document.body).on('click.' + uid, $popup.hider);
      }, 0);
    }
    $popup.on('click', '.close', function (e) {
      e.preventDefault();
      $popup.hideMe();
    });
    $ct.trigger('popup_show', [$popup]);
    if (p.container && p.container.length)
      $popup.detach().appendTo(p.container);
    if (p.pointTo) {
      $popup.setPos(p.pointTo);
    }
    setTimeout(function () {
      $popup.show();
    }, 0);
    return $popup;
  };

  if ($popup.o.delegate) {
    $($popup.o.delegate).on('click', click_target, handler);
  } else {
    $ct.click(handler);
  }

  $popup.setWidth($popup.o.width);

  return $popup;
};

// makes an element into a modal.
// click_target defines the element/elements that trigger the modal.
// currently presumes the given element uses the '.modal' style
// o takes the following optional fields:
//     callback:    a function to run before displaying the modal. Returning
//                  false will cancel the modal.
//     container:   if set the modal will be appended to the container before
//                  being displayed.
//     width:       the width of the modal.
//     delegate:    delegates the click handling of the click_target to the
//                  specified parent element.
//     hideme:      defaults to true; if set to false, modal will not be hidden
//                  when the user clicks outside of it.
//     emptyme:     defaults to false; if set to true, modal will be cleared
//                  after it is hidden.
//     deleteme:    defaults to false; if set to true, popup will be deleted
//                  after it is hidden.
//     close:       defaults to false; if set to true, modal will have a
//                  close button
// note: all options may be overridden and modified by returning them in an
//       object from the callback.
//
// If you want to close all existing modals, use:
//      $('.modal').trigger('close');

$.fn.modal = function (click_target, o) {
  o = o || {};

  let $ct = $(click_target),
    $modal = this;

  $modal.o = $.extend(
    {
      delegate: false,
      callback: false,
      onresize: function () {
        $modal.setPos();
      },
      hideme: true,
      emptyme: false,
      deleteme: false,
      offset: {},
      width: 450,
    },
    o,
  );

  $modal.setWidth = function (w) {
    $modal.css({ width: w });
    return $modal;
  };

  $modal.setPos = function (offset) {
    offset = offset || $modal.o.offset;

    $modal.detach().appendTo('body');
    let toX = offset.x || ($(window).width() - $modal.outerWidth(false)) / 2,
      toY = offset.y || 160;
    $modal.css({
      left: toX + 'px',
      top: toY + 'px',
      right: 'inherit',
      bottom: 'inherit',
      position: 'fixed',
    });
    return $modal;
  };

  $modal.hideMe = function () {
    let p = $modal.o;
    $modal.hide();
    $modal.off();
    $(document.body).off('click newmodal', $modal.hider);
    $(window).off('keydown.lightboxDismiss');
    $(window).on('resize', p.onresize);
    $('.modal-overlay').remove();
    return $modal;
  };

  function handler(e) {
    e.preventDefault();
    let resp = o.callback
      ? o.callback.call($modal, {
          click_target: this,
          evt: e,
        }) !== false
      : true;
    $modal.o = $.extend({ click_target: this }, $modal.o, resp);
    if (resp) {
      $('.modal').trigger('close'); // We don't want two!
      $modal.render();
    }
  }

  $modal.render = function () {
    let p = $modal.o;
    $modal.hider = makeBlurHideCallback($modal);
    if (p.hideme) {
      try {
        setTimeout(function () {
          $('.modal-overlay, .close').on('click modal', $modal.hider);
        }, 0);
      } catch (err) {
        // TODO(Kumar) handle this more gracefully. See bug 701221.
        if (typeof console !== 'undefined') {
          console.error('Could not close modal:', err);
        }
      }
    }
    if (p.close) {
      let close = $('<a>', { class: 'close', text: 'X' });
      $modal.append(close);
    }
    $('.popup').hide();
    $modal.on('click', '.close', function (e) {
      e.preventDefault();
      $modal.trigger('close');
    });
    $modal.on('close', function (e) {
      if (p.emptyme) {
        $modal.empty();
      }
      if (p.deleteme) {
        $modal.remove();
      }
      e.preventDefault();
      $modal.hideMe();
    });
    $ct.trigger('modal_show', [$modal]);
    if (p.container && p.container.length)
      $modal.detach().appendTo(p.container);
    $('<div class="modal-overlay"></div>').appendTo('body');
    $modal.setPos();
    setTimeout(function () {
      $modal.show();
    }, 0);

    $(window)
      .on('resize', p.onresize)
      .on('keydown.lightboxDismiss', function (e) {
        if (e.which == 27) {
          $modal.hideMe();
        }
      });
    return $modal;
  };

  if ($modal.o.delegate) {
    $($modal.o.delegate).on('click', click_target, handler);
  } else {
    $ct.click(handler);
  }

  $modal.setWidth($modal.o.width);

  return $modal;
};

// Slugify
// This allows you to create a line of text with a "Edit" field,
// and swap it out for an editable slug.  For example:
//
// http://mozilla.com/slugname <a>edit</a>
// ..to..
// http://mozilla.com/[editable slug name]

function makeslug(s, delimiter) {
  if (!s) return '';
  let re = new RegExp('[^\\w' + unicode_letters + '\\s-]+', 'g');
  s = $.trim(s.replace(re, ' '));
  s = s.replace(/[-\s]+/g, delimiter || '-').toLowerCase();
  return s;
}

export function show_slug_edit(e) {
  $('#slug_readonly').hide();
  $('#slug_edit').show();
  $('#id_slug').focus();
  e.preventDefault();
}

export function slugify() {
  let $slug = $('#id_slug');
  let url_customized =
    $slug.attr('data-customized') === 0 || !$slug.attr('data-customized');
  if (url_customized || !$slug.val()) {
    let new_slug = makeslug($('#id_name').val());
    if (new_slug !== '') {
      $slug.val(new_slug);
    }
  }
  const name_val = $slug.val();
  $('#slug_value').text($slug.val());
}

// Initializes character counters for textareas.
export function initCharCount() {
  let countChars = function (val, cc) {
    let max = parseInt(cc.attr('data-maxlength'), 10),
      min = parseInt(cc.attr('data-minlength'), 10) || 0,
      // Count \r\n as one character, not two.
      lineBreaks = val.split('\n').length - 1,
      left = max - val.length - lineBreaks,
      count = val.length - lineBreaks,
      output = [];
    if (min || !max) {
      // L10n: {0} is the number of characters entered.
      output.push(
        format(
          ngettext('<b>{0}</b> character', '<b>{0}</b> characters', count),
          [count],
        ),
      );
    }
    if (max) {
      // L10n: {0} is the number of characters left.
      output.push(
        format(
          ngettext(
            '<b>{0}</b> character left',
            '<b>{0}</b> characters left',
            left,
          ),
          [left],
        ),
      );
    }
    cc.html(
      (cc.attr('data-text-prefix') || '') +
        output.join('; ') +
        (cc.attr('data-text-postfix') || '.'),
    ).toggleClass('error', left < 0 || count < min);
  };
  $('.char-count').each(function () {
    let $cc = $(this),
      $form = $(this).closest('form'),
      $el,
      multi = false;
    if ($cc.data('for-names') !== undefined) {
      multi = true;
      let query_string = $cc
        .data('for-names')
        .split(',')
        .map(function (field_name) {
          return (
            'textarea[name^="' +
            field_name +
            '"]:visible, input[name^="' +
            field_name +
            '"]:visible'
          );
        })
        .join(', ');
      $el = $(query_string, $form);
    } else if ($cc.attr('data-for-startswith') !== undefined) {
      $el = $(
        'textarea[id^="' +
          $cc.attr('data-for-startswith') +
          '"]:visible, input[id^="' +
          $cc.attr('data-for-startswith') +
          '"]:visible',
        $form,
      );
    } else {
      $el = $('textarea#' + $cc.attr('data-for'), $form);
    }
    $el
      .on('keyup blur', function () {
        let $this = $(this),
          val;
        if (multi) {
          val = $el
            .filter('[name$="' + $this.attr('lang') + '"]')
            .map(function () {
              return $(this).val();
            })
            .get()
            .join('');
        } else {
          val = $this.val();
        }
        countChars(val, $cc);
      })
      .trigger('blur');
  });
}

// .exists()
// This returns true if length > 0.

$.fn.exists = function (callback, args) {
  let $this = $(this),
    len = $this.length;

  if (len && callback) {
    callback.apply(null, args);
  }
  return len > 0;
};

export function formatFileSize(size) {
  return Intl.NumberFormat(document.documentElement.lang, {
    notation: 'compact',
    style: 'unit',
    unit: 'byte',
    unitDisplay: 'narrow',
  }).format(size);
}

export function validateFileUploadSize() {
  const maxSize = $(this).data('max-upload-size');
  const file = this.files[0];
  const input = $(this).get(0);
  if (file.size > maxSize) {
    input.setCustomValidity(
      format(gettext('Your file exceeds the maximum size of {0}.'), [
        formatFileSize(maxSize),
      ]),
    );
  } else {
    input.setCustomValidity('');
  }
}
