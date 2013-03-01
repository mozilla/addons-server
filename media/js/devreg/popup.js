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
$.fn.popup = function(click_target, o) {
    o = o || {};

    var $ct         = $(click_target),
        $popup      = this,
        uid         = (z.uid++),
        spawned     = 0;

    $popup.o = $.extend({
        delegate:   false,
        callback:   false,
        container:  false,
        hideme:     true,
        emptyme:    false,
        pointTo:    false,
        offset:     {},
        width:      300
    }, o);

    $popup.setWidth = function(w) {
        $popup.css({width: w});
        return $popup;
    };

    $popup.setPos = function(el, offset) {
        offset = offset || $popup.o.offset;
        el = el || $popup.o.pointTo;
        if (!el) return false;
        $popup.detach().appendTo("body");
        var pt  = $(el),
            pos = pt.offset(),
            tw  = pt.outerWidth(false) / 2,
            th  = pt.outerHeight(false),
            pm  = pos.left + tw > $("body").outerWidth(false) / 2,
            os  = pm ? $popup.outerWidth(false) - 84 : 63,
            toX = pos.left + (offset.x || tw) - os,
            toY = pos.top + (offset.y || th) + 4;
        $popup.toggleClass("left", pm);
        $popup.css({
            'left': toX,
            'top': toY,
            'right': 'inherit',
            'bottom': 'inherit'
        });
        $popup.o.pointTo = el;
        return $popup;
    };

    $popup.hideMe = function() {
        $popup.hide();
        $popup.unbind();
        $popup.undelegate();
        $(document.body).unbind('click.'+uid, $popup.hider);
        return $popup;
    };

    function handler(e) {
        e.preventDefault();
        spawned = e.timeStamp;
        var resp = o.callback ? (o.callback.call($popup, {
                click_target: this,
                evt: e
            })) : true;
        $popup.o = $.extend({click_target: this}, $popup.o, resp);
        if (resp) {
            $popup.render();
        }
    }

    $popup.render = function() {
        var p = $popup.o,
            hideCallback = makeBlurHideCallback($popup);
        $popup.hider = function(e) {
            if (e.timeStamp != spawned) {
                hideCallback.call(this, e);
            }
        };
        if (p.hideme) {
            setTimeout(function(){
                $(document.body).bind('click.'+uid, $popup.hider);
            }, 0);
        }
        $popup.delegate('.close', 'click', function(e) {
            e.preventDefault();
            $popup.hideMe();
        });
        $ct.trigger("popup_show", [$popup]);
        if (p.container && p.container.length)
            $popup.detach().appendTo(p.container);
        if (p.pointTo) {
            $popup.setPos(p.pointTo);
        }
        setTimeout(function(){
            $popup.show();
        }, 0);
        return $popup;
    };

    if ($popup.o.delegate) {
        $($popup.o.delegate).delegate(click_target, "click", handler);
    } else {
        $ct.click(handler);
    }

    $popup.setWidth($popup.o.width);

    return $popup;
};