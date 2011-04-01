$(function() {
    $(window).bind("orientationchange", function(e) {
        setTimeout(function() {
            $("details").truncate({textEl: ".desc"});
        }, 100);
    });
    $("details").truncate({textEl: ".desc"});

    $(".vtruncate").truncate({dir: 'v'});

    $('form.go').change(function() { this.submit(); })
        .find('button').hide();

    $('span.emaillink').each(function() {
        $(this).find('.i').remove();
        var em = $(this).text().split('').reverse().join('');
        $(this).prev('a').attr('href', 'mailto:' + em);
    });

    $("#sort-menu").delegate("select", "change", function() {
        $el = $(this).find("option[selected]");
        if ($el.attr("data-url")) {
            window.location = $el.attr("data-url");
        }
    });

    $("#learnmore, #learnmore-msg").click(_pd(function() {
        $("#learnmore-msg").toggleClass("show");
        $("#learnmore").blur();
    }));

    $(".carousel").each(function() {
        var $self = $(this),
            $strip = $("ul", $self),
            $prev = $(".prev", $self),
            $next = $(".next", $self),
            prop = $("body").hasClass("html-rtl") ? "right" : "left",
            currentPos = 0,
            maxPos = $("li", $strip).length/2-1;
        function render(pos) {
            currentPos = Math.min(Math.max(0, pos), maxPos);
            $strip.css(prop, currentPos * -100 + "%");
            $prev.toggleClass("disabled", currentPos == 0);
            $next.toggleClass("disabled", currentPos == maxPos);
        }
        $self.bind("swipeleft", function() {
            render(currentPos+1);
        }).bind("swiperight", function() {
            render(currentPos-1);
        });
        $next.click(_pd(function() {
            render(currentPos+1);
            $next.blur();
        }));
        $prev.click(_pd(function() {
            render(currentPos-1);
            $prev.blur();
        }));
        render(0);
    });

    $(".expando").each(function() {
        var $trigger = $(this),
            $managed = $($trigger.attr("href"));
        $managed.addClass("expando-managed");
        $trigger.click(_pd(function () {
            $managed.toggleClass("expand");
            if ($managed.hasClass("expand")) {
                $managed.css("height", $managed[0].scrollHeight);
            } else {
                $managed.css("height", 0);
            }
            $trigger.toggleClass("expand").blur();
        }));
    });

    $(".tabs").each(function() {
        var $strip=$(this),
            $managed = $("#"+$strip.attr("data-manages")),
            isManaged = $managed.length,
            isSlider = isManaged && $managed.hasClass("slider"),
            prop = $("body").hasClass("html-rtl") ? "right" : "left",
            current = $strip.find(".selected a").attr("href");
        if (isManaged) {
            if (isSlider)
                $managed.css("height", $managed.find(current).outerHeight() + "px");
        } else {
            $managed = $(document.body);
        }
        $strip.delegate("a", "click", function(e) {
            e.preventDefault();
            var $tgt = $(this),
                href = $tgt.attr("href"),
                $pane = $managed.find(href);
            if (current != href && $pane.length && $pane.is(".tab-pane")) {
                current = href;
                $managed.find(".tab-pane").removeClass("selected");
                $pane.addClass("selected");
                $strip.find("li").removeClass("selected");
                $tgt.parent().addClass("selected");
                $tgt.blur();
                if (isManaged && isSlider && $pane.index() >= 0) {
                    $managed.css(prop, ($pane.index() * -100) + "%");
                    $managed.css("height", $pane.outerHeight() + "px");
                }
            }
        });
    });
    (function() {
        var $document = $(document),
            $lightbox = $("#lightbox"),
            $content = $("#lightbox .content"),
            $caption = $("#lightbox .caption"),
            current, $strip,
            lbImage = template('<img id="preview{0}" src="{1}">');
        if (!$lightbox.length) return;
        function posLightbox() {
            $lightbox.css({
                "top": $document.scrollTop()-1,
                "left": $document.scrollLeft()
            });
            var $img = $lightbox.find("img");
            $img.each(function () {
                var $img = $(this);
                $img.css({
                    "margin-top": -$img.height()/2,
                    "margin-left": -$img.width()/2,
                    "top": "50%",
                    "left": "50%"
                });
            });
        }
        $document.scroll(posLightbox);
        $(window).bind("orientationchange", posLightbox);
        function showLightbox() {
            $lightbox.show();
            showImage(this);
            //I want to ensure the lightbox is painted before fading it in.
            setTimeout(function () {
                $lightbox.addClass("show");
                posLightbox();
            },0);
        }
        function showImage(a) {
            var $a = $(a),
                $oldimg = $lightbox.find("img");
            current = $a.parent().index();
            $strip = $a.closest("ul").find("li");
            var $img = $("#preview"+current);
            if ($img.length) {
                posLightbox();
                $oldimg.css("opacity", 0);
                $img.css("opacity", 1);
            } else {
                $img = $(lbImage([current, $a.attr("href")]));
                $content.append($img);
                $img.load(function(e) {
                    posLightbox();
                    $oldimg.css("opacity", 0);
                    $img.css("opacity", 1);
                    for (var i=0; i<$strip.length; i++) {
                        if (i != current) {
                            var $p = $strip.eq(i).find("a");
                            $content.append(lbImage([i, $p.attr("href")]));
                        }
                    }
                });
            }
            $caption.text($a.attr("title"));
            $lightbox.find(".control").removeClass("disabled");
            if (current < 1) {
                $lightbox.find(".control.prev").addClass("disabled");
            }
            if (current == $strip.length-1){
                $lightbox.find(".control.next").addClass("disabled");
            }
        }
        $("#lightbox .next").click(_pd(function() {
            if (current < $strip.length-1) {
                showImage($strip.eq(current+1).find("a"));
                $(this).blur();
            }
        }));
        $("#lightbox .prev").click(_pd(function() {
            if (current > 0) {
                showImage($strip.eq(current-1).find("a"));
                $(this).blur();
            }
        }));
        $(".carousel ul a").click(_pd(showLightbox));
        $("#lightbox .close, #lightbox .content").click(_pd(function() {
            $lightbox.removeClass("show");
            // We can't trust transitionend to fire in all cases.
            setTimeout(function() {
                $lightbox.hide();
            }, 500);
        }));
        $document.scroll();
    })();

    $("#eula .negative").click(_pd(z.eula.dismiss));
    $("#eula .affirmative").click(_pd(z.eula.dismiss));

    //review truncation
    if ($(".review").length) {
        $(".review p").each(function() {
            var $el = $(this);
            if ($el.hasClass("truncated")) {
                $el.closest(".review").find(".readmore").css("display", "block");
            }
        });
        $("#content").delegate(".review .readmore", "click", _pd(function(e) {
            var $el = $(this),
                $revBody = $el.closest(".review").find("p");
            $el.hide();
            $revBody.removeClass("truncated")
                    .html(unescape($revBody.attr("oldtext")))
                    .css("max-height", "none");
        }));
    }
});

$(".desktop-link").attr("href", window.location).click(function() {
    $.cookie("mamo", "off", {expires:30});
});

$(".moz-menu .tab a").click(_pd(function() {
    $(".moz-menu").toggleClass("expand");
    this.blur();
}));

$("#sort-menu .label").click(_pd(function() {
    $("#sort-menu").toggleClass("expand");
    this.blur();
}));

z.eula = (function(){
    var $eula = $("#eula"),
        $body = $(document.body),
        currentPos;
    function show() {
        if ($eula.length && !$body.hasClass("locked")) {
            currentPos = $(document).scrollTop() || 1;
            $eula.show();
            $body.addClass("locked");
        }
    }
    function dismiss() {
        if ($eula.length && $body.hasClass("locked")) {
            $eula.hide();
            $body.removeClass("locked");
            $(document).scrollTop(currentPos);
        }
    }
    return {
        show: show,
        dismiss: dismiss,
        acceptButton: $("#eula-menu .affirmative")
    };
})();
