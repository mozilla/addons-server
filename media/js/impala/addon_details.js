$(function () {
    $(".previews").zCarousel({
        btnNext: ".previews .next",
        btnPrev: ".previews .prev",
        itemsPerPage: 3
    });
    (function() {
        var $document = $(document),
            $lightbox = $("#lightbox"),
            $content = $("#lightbox .content"),
            $caption = $("#lightbox .caption"),
            current, $strip,
            lbImage = template('<img id="preview{0}" src="{1}">');
        if (!$lightbox.length) return;
        function showLightbox() {
            $lightbox.show();
            showImage(this);
            //I want to ensure the lightbox is painted before fading it in.
            setTimeout(function () {
                $lightbox.addClass("show");
            },0);
        }
        function showImage(a) {
            var $a = $(a),
                $oldimg = $lightbox.find("img");
            current = $a.parent().index();
            $strip = $a.closest("ul").find("li");
            var $img = $("#preview"+current);
            if ($img.length) {
                $oldimg.css("opacity", 0);
                $img.css({
                    "opacity": 1,
                    'margin-top': (525-$img.height())/2+'px',
                    'margin-left': (700-$img.width())/2+'px'
                });
            } else {
                $img = $(lbImage([current, $a.attr("href")]));
                $content.append($img);
                $img.load(function(e) {
                    $oldimg.css("opacity", 0);
                    $img.css({
                        "opacity": 1,
                        'margin-top': (525-$img.height())/2+'px',
                        'margin-left': (700-$img.width())/2+'px'
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
        $(".previews ul a").click(_pd(showLightbox));
        $("#lightbox .close, #lightbox .content").click(_pd(function() {
            $lightbox.removeClass("show");
            // We can't trust transitionend to fire in all cases.
            setTimeout(function() {
                $lightbox.hide();
            }, 500);
        }));
        $document.scroll();
    })();

    if ($('#review-add-box').exists())
        $('#review-add-box').modal('#add-review', { width: '650px' });

    if ($('#privacy-policy').exists())
        $('#privacy-policy').modal('.privacy-policy', { width: '500px' });
});