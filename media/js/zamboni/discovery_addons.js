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

    this.each(function() {
        var $self = $(this),
            $strip = $(".slider", $self),
            $lis = $strip.find(".panel"),
            $prev = $(o.btnPrev),
            $next = $(o.btnNext),
            prop = $("body").hasClass("html-rtl") ? "right" : "left",
            currentPos = 0,
            maxPos = Math.ceil($lis.length / o.itemsPerPage) - 1;
        function render(pos) {
            if (o.circular) {
                currentPos = pos;
                if ($strip.hasClass("noslide")) {
                    currentPos = (pos > maxPos+o.itemsPerPage) ? (o.itemsPerPage) : (pos < o.itemsPerPage ? maxPos+o.itemsPerPage : pos);
                }
            } else {
                currentPos = Math.min(Math.max(0, pos), maxPos);
            }
            $strip.css(prop, currentPos * -100 + "%");
            $prev.toggleClass("disabled", currentPos == 0 && !o.circular);
            $next.toggleClass("disabled", currentPos == maxPos && !o.circular);
            setTimeout(function() {
                $strip.removeClass("noslide");
            }, 0);
        }
        $next.click(_pd(function() {
            render(currentPos+1);
        }));
        $prev.click(_pd(function() {
            render(currentPos-1);
        }));

        // Strip text nodes
        var cn = $strip[0].childNodes;
        for(var i = 0; i < cn.length; i++) {
            if (cn[i].nodeType == 3) {
                $strip[0].removeChild(cn[i]);
            };
        }

        if (o.circular) {
            $strip.prepend($lis.slice(-o.itemsPerPage).clone().addClass("cloned"))
                  .append($lis.slice(0,o.itemsPerPage).clone().addClass("cloned"));
            render(o.itemsPerPage);
            $strip.bind("transitionend", function() {
                if (currentPos > maxPos+o.itemsPerPage || currentPos < o.itemsPerPage) {
                    $strip.addClass("noslide");
                    setTimeout(function() {
                        render(currentPos);
                    }, 0);
                }
            });
        } else {
            render(0);
        }
    });
};

})(jQuery);


$(document).ready(function(){
    if ($(".detail").length) {
        initDetail();
    }
});


function debounce(fn, ms, ctxt) {
    var ctx = ctxt || window;
    var to, del = ms, fun = fn;
    return function () {
        var args = arguments;
        clearTimeout(to);
        to = setTimeout(function() {
            fun.apply(ctx, args);
        }, del);
    };
}

function initDetail() {
    $(".install-action a").attr("target", "_self");

    // Replace with the URL back to the discovery promo pane.
    $("p#back a").attr("href", Storage.get("discopane-url"));

    $("#images").fadeIn("slow").addClass("js").zCarousel({
        btnNext: "#images .nav-next a",
        btnPrev: "#images .nav-prev a",
        itemsPerPage: 3
    });
    $(".addon-info").addClass("js");

    // Set up the lightbox.
    var lb_baseurl = z.media_url + "img/jquery-lightbox/";
    $("#images .panel a").lightBox({
        overlayOpacity: 0.6,
        imageBlank: lb_baseurl + "lightbox-blank.gif",
        imageLoading: lb_baseurl + "lightbox-ico-loading.gif",
        imageBtnClose: "",
        imageBtnPrev: "",
        imageBtnNext: "",
        containerResizeSpeed: 350
    });
}
