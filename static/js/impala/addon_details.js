$(function () {
    if (!$("body").hasClass('addon-details')) return;

    if ($("body.restyle").length === 1) {
        $('#background-wrapper').height(
            $('.amo-header').height() +
            ($('.notification-box').length ? 80 : 0) +
            $('.addon-description-header').height() + 20
        );
    }

    $(".previews").zCarousel({
        btnNext: ".previews .next",
        btnPrev: ".previews .prev",
        itemsPerPage: 3
    });
    (function() {
        var $document = $(document),
            $lightbox = $("#lightbox"),
            $content = $("#lightbox .content"),
            $caption = $("#lightbox .caption span"),
            $previews = $('.previews'),
            current, $strip,
            lbImage = template('<img id="preview{0}" src="{1}" alt="">');
        if (!$lightbox.length) return;
        function showLightbox() {
            $lightbox.show();
            showImage(this);
            $(window).on('keydown.lightboxDismiss', function(e) {
                switch(e.which) {
                    case z.keys.ESCAPE:
                        e.preventDefault();
                        hideLightbox();
                        break;
                    case z.keys.LEFT:
                        e.preventDefault();
                        showPrev();
                        break;
                    case z.keys.RIGHT:
                        e.preventDefault();
                        showNext();
                        break;
                }
            });
            //I want to ensure the lightbox is painted before fading it in.
            setTimeout(function () {
                $lightbox.addClass("show");
            },0);
        }
        function hideLightbox() {
            $lightbox.removeClass("show");
            // We can't trust transitionend to fire in all cases.
            setTimeout(function() {
                $lightbox.hide();
            }, 500);
            $(window).off('keydown.lightboxDismiss');
        }
        function showImage(a) {
            var $a = $(a),
                $oldimg = $lightbox.find("img");
            current = $a.parent().index();
            $strip = $a.closest("ul").find("li");
            $previews.find('.panel').removeClass('active')
                     .eq(current).addClass('active');
            var $img = $("#preview"+current);
            if ($img.length) {
                $oldimg.css({"opacity": "0", "z-index": "0"});
                $img.css({
                    "opacity": "1", "z-index": "1"
                });
            } else {
                $img = $(lbImage([current, $a.attr("href")]));
                $content.append($img);
                $img.on("load", function(e) {
                    $oldimg.css({"opacity": "0", "z-index": "0"});
                    $img.css({
                        "opacity": "1", "z-index": "1"
                    });
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
        function showNext() {
            if (current < $strip.length-1) {
                showImage($strip.eq(current+1).find("a"));
                if (!this.window) {
                    $(this).blur();
                }
            }
        }
        function showPrev() {
            if (current > 0) {
                showImage($strip.eq(current-1).find("a"));
                if (!this.window) {
                    $(this).blur();
                }
            }
        }
        $("#lightbox .next").click(_pd(showNext));
        $("#lightbox .prev").click(_pd(showPrev));
        $(".previews ul a").click(_pd(showLightbox));
        $('#lightbox').click(_pd(function(e) {
            if ($(e.target).is('.close, #lightbox')) {
                hideLightbox();
            }
        }));
    })();

    if ($('#more-webpage').exists()) {
        var $moreEl = $('#more-webpage');
            url = $moreEl.attr('data-more-url');
        $.get(url, function(resp) {
            var $document = $(document);
            var scrollTop = $document.scrollTop();
            var origHeight = $document.height();

            // We need to correct scrolling position if the user scrolled down
            // already (e.g. by using a link with anchor). This correction is
            // only necessary if the scrolling position is below the element we
            // replace or the user scrolled down to the bottom of the document.
            var shouldCorrectScrolling = scrollTop > $moreEl.offset().top;
            if (scrollTop && scrollTop >= origHeight - $(window).height()) {
                shouldCorrectScrolling = true;
            }

            // Strip the leading whitespace so that $() treats this as html and
            // not a selector.
            var $newContent = $(resp.trim());
            $moreEl.replaceWith($newContent);
            $newContent.find('.listing-grid h3').truncate( {dir: 'h'} );
            $newContent.find('.install').installButton();
            $newContent.find('.listing-grid').each(listing_grid);
            $('#reviews-link').addClass('scrollto').attr('href', '#reviews');

            if (shouldCorrectScrolling) {
                // User scrolled down already, adjust scrolling position so
                // that the same content stays visible.
                var heightDifference = $document.height() - origHeight;
                $document.scrollTop(scrollTop + heightDifference);
            }
        });
    }

    if ($('#review-add-box').exists())
        $('#review-add-box').modal('#add-review', { delegate: '#page', width: '650px' });

    if ($('#privacy-policy').exists())
        $('#privacy-policy').modal('.privacy-policy', { width: '500px' });
    if ($('#webext-permissions').exists())
        $('#webext-permissions').modal('.webext-permissions', { width: '500px' });

    // Show add-on ID when icon is clicked
    if ($("#addon[data-id], #persona[data-id]").exists()) {
        $("#addon .icon").click(function() {
            window.location.hash = "id=" + $("#addon, #persona").attr("data-id");
        });
    }

    $('#abuse-modal').modal('#report-abuse', {delegate: '#page'});
});
