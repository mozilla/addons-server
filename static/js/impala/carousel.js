/**
 * zCarousel: like jCarouselLite, but good.
 * by potch
 *
 * handles fluid layouts like a champ!
 */

(function($) {

$.fn.zCarousel = function(o) {
    o = $.extend({
        itemsPerPage: 1,
        circular: false
    }, o);

    var $self = $(this).eq(0),
        $strip = $(".slider", $self),
        $lis = $strip.find(".panel"),
        $prev = $(o.btnPrev),
        $next = $(o.btnNext),
        prop = o.prop || ($("body").hasClass("html-rtl") ? "right" : "left"),
        currentPos = 0,
        maxPos = Math.ceil($lis.length / o.itemsPerPage);

    if (!$strip.length) return $self;

    function render(pos) {
        if (o.circular) {
            currentPos = pos > maxPos+1 ? pos-maxPos : (pos < 0 ? pos+maxPos : pos);
            if ($strip.hasClass("noslide")) {
                currentPos = (pos > maxPos) ? 1 : (pos < 1 ? maxPos : pos);
            }
        } else {
            currentPos = Math.min(Math.max(0, pos), maxPos-1);
        }
        $strip.css(prop, currentPos * -100 + "%");
        $prev.toggleClass("disabled", currentPos == 0 && !o.circular);
        $next.toggleClass("disabled", currentPos == maxPos-1 && !o.circular);
        //wait for paint to clear the class. lame.
        setTimeout(function() {
            $strip.removeClass('noslide');
        }, 0);
    }

    //wire up controls.
    function fwd() {
        render(currentPos+1);
    }
    function prev() {
        render(currentPos-1);
    }
    $next.click(_pd(fwd));
    $prev.click(_pd(prev));
    $self.gofwd = fwd;
    $self.goback = prev;

    // Strip text nodes so inline-block works properly.
    var cn = $strip[0].childNodes;
    for(var i = 0; i < cn.length; i++) {
        if (cn[i].nodeType == 3) {
            $strip[0].removeChild(cn[i]);
        };
    }

    if (o.circular) {
        //pad the beginning with a page from the end vice-versa.
        $strip.prepend($lis.slice(-o.itemsPerPage).clone().addClass("cloned"))
              .append($lis.slice(0,o.itemsPerPage).clone().addClass("cloned"));
        $strip.addClass('noslide');
        $strip.on("transitionend webkitTransitionEnd", function() {
            if (currentPos > maxPos || currentPos < 1) {
                $strip.addClass("noslide");
                setTimeout(function() {
                    render(currentPos);
                }, 0);
            }
        });
        render(o.itemsPerPage);
    } else {
        render(0);
    }
    return $self;
};

})(jQuery);
