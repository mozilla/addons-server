/*
JS included by any *remote* web app to enable in-app payments via Mozilla Market
*/


// Using jQuery for easy prototyping...
if (typeof $ === 'undefined') {
    console.log('This prototype currently requires jQuery');
}


(function(exports) {
"use strict";


var server;


exports.buy = function(signedRequest, onPaySuccess, onPayFailure, options) {
    modalFromURL(server + '/payments/pay_start',
                 {data: {req: signedRequest}});
};


// Delete all of this code. This is just a prototype for demos.


setTimeout(function() {
    $('script').each(function(i, elem) {
        var src = $(elem).attr('src');
        if (src.search('mozmarket.js') != -1) {
            server = src.replace(/(https?:\/\/[^\/]+).*/g, '$1');
        }
    });
    $.ajax({type: 'GET',
            url: server + '/payments/inject_styles',
            dataType: 'jsonp',
            success: function(html) {
                $('body').append(html);
            },
            error: function(xhr, textStatus, errorThrown) {
                console.error('ERROR', textStatus, xhr.status, errorThrown);
            }
    });
}, 1);


$(function() {
  $('form.ajax-submit, .ajax-submit form').live('submit', function() {
      var $form = $(this),
          $parent = $form.is('.ajax-submit') ? $form : $form.closest('.ajax-submit'),
          params = $form.serializeArray();
      $form.find('.submit, button[type=submit], submit').attr('disabled', true).addClass('loading-submit');
      $.ajax({type: 'GET',
              url: $form.attr('action'),
              data: params,
              dataType: 'jsonp',
              success: function(html) {
                  var $replacement = $(html);
                  $parent.replaceWith($replacement);
                  $replacement.trigger('ajax-submit-loaded');
                  $replacement.find('.ajax-submit').trigger('ajax-submit-loaded');
              },
              error: function(xhr, textStatus, errorThrown) {
                  console.error('ERROR', textStatus, xhr.status, errorThrown);
              }
      });
      return false;
  });
});


// These are internal helper methods that can go away once the implementation
// changes.

// Modal from URL. Pass in a URL, and load it in a modal.
function modalFromURL(url, settings) {
    var a = $('<a>'),
        defaults = {'deleteme': true, 'close': true},
        settings = settings || {},
        data = settings['data'] || {},
        callback = settings['callback'];

    delete settings['callback'];
    settings = $.extend(defaults, settings);

    var inside = $('<div>', {'class': 'modal-inside', 'text': 'Loading...'}),
        modal = $("<div>", {'class': 'modal'}).modal(a, settings);

    modal.append(inside);
    a.trigger('click');

    $.ajax({type: 'GET',
            url: url,
            data: data,
            dataType: 'jsonp',
            success: function(html) {
                modal.appendTo('body')
                inside.html("").append(html);
                if(callback) {
                    callback.call(modal);
                }
            },
            error: function(xhr, textStatus, errorThrown) {
                console.error('ERROR', textStatus, xhr.status, errorThrown);
            }
    });
    return modal;
}


})(typeof exports === 'undefined' ? (this.mozmarket = {}) : exports);



$.fn.modal = function(click_target, o) {
    o = o || {};

    var $ct         = $(click_target),
        $modal      = this;

    $modal.o = $.extend({
        delegate:   false,
        callback:   false,
        onresize:   function(){$modal.setPos();},
        hideme:     true,
        emptyme:    false,
        deleteme:   false,
        offset:     {},
        width:      450,
        target:     'body'
    }, o);

    $modal.setWidth = function(w) {
        $modal.css({width: w});
        return $modal;
    };

    $modal.setPos = function(offset) {
        offset = offset || $modal.o.offset;

        $modal.detach().appendTo($modal.o.target);
        var toX = ($(window).width() - $modal.outerWidth()) / 2,
            toY = $(window).scrollTop() + 26; //distance from top of the window
        $modal.css({
            'left': toX,
            'top': toY + 'px',
            'right': 'inherit',
            'bottom': 'inherit',
            'position': 'absolute'
        });
        return $modal;
    };

    $modal.hideMe = function() {
        var p = $modal.o;
        $modal.hide();
        $modal.unbind();
        $modal.undelegate();
        $(document.body).unbind('click newmodal', $modal.hider);
        $(window).unbind('keydown.lightboxDismiss');
        $(window).bind('resize', p.onresize);
        $('.modal-overlay').remove();
        return $modal;
    };

    function handler(e) {
        e.preventDefault();
        var resp = o.callback ? (o.callback.call($modal, {
                click_target: this,
                evt: e
            })) !== false : true;
        $modal.o = $.extend({click_target: this}, $modal.o, resp);
        if (resp) {
            $('.modal').trigger('close'); // We don't want two!
            $modal.render();
        }
    }

    // returns an event handler that will hide/unbind an element when a click is
    // registered outside itself.
    function makeBlurHideCallback(el) {
        var hider = function(e) {
            _root = el.get(0);
            // Bail if the click was somewhere on the popup.
            if (e) {
                if (e.type == 'click' &&
                    _root == e.target ||
                    _.indexOf($(e.target).parents(), _root) != -1) {
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

    $modal.render = function() {
        var p = $modal.o;
        $modal.hider = makeBlurHideCallback($modal);
        if (p.hideme) {
            try {
                setTimeout(function(){
                    $(document.body).bind('click modal', $modal.hider);
                }, 0);
            } catch (err) {
                // TODO(Kumar) handle this more gracefully. See bug 701221.
                if (typeof console !== 'undefined') {
                    console.error('Could not close modal:', err);
                }
            }
        }
        if (p.close) {
            var close = $("<a>", {'class': 'close', 'text': 'X'});
            $modal.append(close);
        }
        $('.popup').hide();
        $modal.delegate('.close', 'click', function(e) {
            e.preventDefault();
            $modal.trigger('close');
        });
        $modal.bind('close', function(e) {
            if (p.emptyme) {
                $modal.empty();
            }
            if (p.deleteme) {
                $modal.remove();
            }
            e.preventDefault();
            $modal.hideMe();
        });
        $ct.trigger("modal_show", [$modal]);
        if (p.container && p.container.length)
            $modal.detach().appendTo(p.container);
        $('<div class="modal-overlay"></div>').appendTo($modal.o.target);
        $modal.setPos();
        setTimeout(function(){
            $modal.show();
        }, 0);

        $(window).bind('resize', p.onresize)
        .bind('keydown.lightboxDismiss', function(e) {
            if (e.which == 27) {
                $modal.hideMe();
            }
        });
        return $modal;
    };

    if ($modal.o.delegate) {
        $($modal.o.delegate).delegate(click_target, "click", handler);
    } else {
        $ct.click(handler);
    }

    $modal.setWidth($modal.o.width);

    return $modal;
};
