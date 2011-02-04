/**
 * jCarouselLite - jQuery plugin to navigate images/any content in a carousel style widget.
 * @requires jQuery v1.2 or above
 *
 * http://gmarwaha.com/jquery/jcarousellite/
 *
 * Copyright (c) 2007 Ganeshji Marwaha (gmarwaha.com)
 * Dual licensed under the MIT and GPL licenses:
 * http://www.opensource.org/licenses/mit-license.php
 * http://www.gnu.org/licenses/gpl.html
 *
 * Version: 1.0.1
 * Note: Requires jquery 1.2 or above from version 1.0.1
 */

(function($) {
$.fn.jCarouselLite = function(o) {
    o = $.extend({
        btnPrev: null,
        btnNext: null,
        btnGo: null,
        mouseWheel: false,
        auto: null,

        speed: 200,
        easing: null,

        vertical: false,
        circular: true,
        visible: 3,
        start: 0,
        scroll: 1,

        beforeStart: null,
        afterEnd: null
    }, o || {});

    return this.each(function() {
        // Returns the element collection. Chainable.

        var running = false,
            animCss = o.vertical ? "top" : "left",
            sizeCss = o.vertical ? "height" : "width",
            div = $(this),
            ul = $(".slider", div),
            tLi = $(".panel", ul),
            tl = tLi.size(),
            v = o.visible;

        if(o.circular) {
            ul.prepend(tLi.slice(tl-v-1+1).clone())
              .append(tLi.slice(0,v).clone());
            o.start += v;
        }

        var li = $(".panel", ul), itemLength = li.size(), curr = o.start;
        div.css("visibility", "visible");

        li.css({"float": o.vertical ? "none" : "left"});
        ul.css({margin: "0", padding: "0", position: "relative", "list-style-type": "none", "z-index": "1"});
        div.css({overflow: "hidden", position: "relative", "z-index": "2", left: "0"});

        // Full li size (including margin, used for animation).
        var liSize = o.vertical ? li.outerHeight(true) : li.outerWidth(true);
        // Size of full ul (total length, not just for the visible items).
        var ulSize = liSize * itemLength;
        // Size of entire div (total length, for only the visible items).
        var divSize = liSize * v;

        li.css({width: li.width(), height: li.height()});
        ul.css(sizeCss, ulSize+"px").css(animCss, -(curr*liSize));

        // Width of the DIV. length of visible images.
        div.css(sizeCss, divSize+"px");

        if(o.btnPrev) {
            $(o.btnPrev).click(function() {
                return go(curr-o.scroll);
            });
            if (!o.circular) {
                $(o.btnPrev).addClass("disabled");
            }
        }

        if(o.btnNext) {
            $(o.btnNext).click(function() {
                return go(curr+o.scroll);
            });
            if (!o.circular && itemLength < o.visible) {
                $(o.btnNext).addClass("disabled");
            }
        }

        if(o.btnGo)
            $.each(o.btnGo, function(i, val) {
                $(val).click(function() {
                    return go(o.circular ? o.visible+i : i);
                });
            });

        if(o.mouseWheel && div.mousewheel)
            div.mousewheel(function(e, d) {
                return d>0 ? go(curr-o.scroll) : go(curr+o.scroll);
            });

        if(o.auto)
            setInterval(function() {
                go(curr+o.scroll);
            }, o.auto+o.speed);

        function vis() {
            return li.slice(curr).slice(0,v);
        };

        function go(to) {
            if(!running) {

                if(o.beforeStart)
                    o.beforeStart.call(this, vis());

                if(o.circular) {            // If circular we are in first or last, then goto the other end
                    if(to<=o.start-v-1) {           // If first, then goto last
                        ul.css(animCss, -((itemLength-(v*2))*liSize)+"px");
                        // If "scroll" > 1, then the "to" might not be equal to the condition; it can be lesser depending on the number of elements.
                        curr = to==o.start-v-1 ? itemLength-(v*2)-1 : itemLength-(v*2)-o.scroll;
                    } else if(to>=itemLength-v+1) { // If last, then goto first
                        ul.css(animCss, -( (v) * liSize ) + "px" );
                        // If "scroll" > 1, then the "to" might not be equal to the condition; it can be greater depending on the number of elements.
                        curr = to==itemLength-v+1 ? v+1 : v+o.scroll;
                    } else curr = to;
                } else {                    // If non-circular and to points to first or last, we just return.
                    if(to<0 || to>itemLength-v) return;
                    else curr = to;
                }                           // If neither overrides it, the curr will still be "to" and we can proceed.

                running = true;

                ul.animate(
                    animCss == "left" ? { left: -(curr*liSize) } : { top: -(curr*liSize) } , o.speed, o.easing,
                    function() {
                        if(o.afterEnd)
                            o.afterEnd.call(this, vis());
                        running = false;
                    }
                );
                // Disable buttons when the carousel reaches the last/first,
                // and enable when not.
                if(!o.circular) {
                    $(o.btnPrev + "," + o.btnNext).removeClass("disabled");
                    $( (curr-o.scroll<0 && o.btnPrev)
                        ||
                       (curr+o.scroll > itemLength-v && o.btnNext)
                        ||
                       []
                     ).addClass("disabled");
                }

            }
            return false;
        };

        // Change panel widths on resize to keep the page liquid
        $(window).resize(function(){
            setPanelWidth("both");
            liSize = o.vertical ? li.outerHeight(true) : li.outerHeight(true);
            ul.css(sizeCss, ulSize+"px").css(animCss, -(curr*liSize));
        });

    });
};

function css(el, prop) {
    return parseInt($.css(el[0], prop)) || 0;
};

})(jQuery);


$(document).ready(function(){
    $(".install-action a").attr("target", "_self");
    $(".detail header p.back a").click(function(e) {
        e.preventDefault();
        history.go(parseInt($(this).attr('data-history')));
    });

    // Set up the carousel.
    $("#main-feature").fadeIn("slow").addClass("js").jCarouselLite({
        btnNext: "#main-feature .nav-next a",
        btnPrev: "#main-feature .nav-prev a",
        visible: 1
    });
    $("#images").fadeIn("slow").addClass("js").jCarouselLite({
        btnNext: "#images .nav-next a",
        btnPrev: "#images .nav-prev a",
        circular: false
    });
    $(".addon-info").addClass("js");

    // Set up the lightbox.
    var lb_baseurl = document.body.getAttribute("data-media-url") + "img/jquery-lightbox/";
    $("#images li.panel a[rel=jquery-lightbox]").lightBox({
        overlayOpacity: 0.6,
        imageBlank: lb_baseurl + "lightbox-blank.gif",
        imageLoading: lb_baseurl + "lightbox-ico-loading.gif",
        imageBtnClose: "",
        imageBtnPrev: "",
        imageBtnNext: "",
        containerResizeSpeed: 350
    });

    setPanelWidth("detail");
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


function setPanelWidth(section) {
    // Set the width of panels (jCarousel requires a pixel width but our page
    // is liquid, so we'll set the width in px on pageload and on resize).
    if (section == "both" || section == "detail") {
        var panelWidth = $("#main").width();
        $("#main-feature, #main-feature .panel, #images").css({width: panelWidth});
        // We show three images at a time, so the width of each is 1/3 minus a
        // right margin of 10px.
        $("#images .panel").css({width: panelWidth / 3 - 10});
    }
    if (section == "both" || section == "pane") {
        var galleryWidth = $("#recs .gallery").width();
        $("#recs .gallery .panel").css({
            "width": 0.3 * galleryWidth,
            "margin-right": 0.05 * galleryWidth
        });
    }
}
