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

$.fn.modal = function(click_target, o) {
    o = o || {};

    var $ct          = $(click_target),
        $modal       = this,
        forcedOffset = 60; //distance from top of the window

    $modal.o = $.extend({
        delegate:   false,
        callback:   false,
        onresize:   function(){$modal.setPos();},
        hideme:     true,
        emptyme:    false,
        deleteme:   false,
        offset:     {},
        width:      450
    }, o);

    $modal.setWidth = function(w) {
        $modal.css({width: w});
        return $modal;
    };

    $modal.setPos = function(offset) {
        offset = offset || $modal.o.offset;

        $modal.detach().appendTo("body");
        var toX = (z.win.width() - $modal.outerWidth(false)) / 2,
            toY = z.win.scrollTop() + forcedOffset;
        $modal.css({
            'left': toX + 'px',
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
        z.body.unbind('click newmodal', $modal.hider);
        z.win.unbind('keydown.lightboxDismiss')
             .bind('resize', p.onresize);
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

    $modal.render = function() {
        var p = $modal.o;
        $modal.hider = makeBlurHideCallback($modal);
        if (p.hideme) {
            try {
                setTimeout(function(){
                    $('#site-header, #page, #site-footer'
                     ).bind('click modal', $modal.hider);
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

        // Bind hider to close button.
        var hider = function(e) {
            if (p.emptyme) {
                $modal.empty();
            }
            if (p.deleteme) {
                $modal.remove();
            }
            e.preventDefault();
            $modal.hideMe();
        };
        $('.close').bind('click', hider);
        $modal.bind('close', function(e) {
            hider(e);
        });

        $ct.trigger("modal_show", [$modal]);
        if (p.container && p.container.length)
            $modal.detach().appendTo(p.container);
        $('<div class="modal-overlay"></div>').appendTo('body');
        $modal.setPos();
        setTimeout(function(){
            $modal.show();
        }, 0);

        z.win.bind('resize', p.onresize)
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
