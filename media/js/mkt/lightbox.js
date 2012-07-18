(function() {
    var $document = $(document),
        $lightbox = $('#lightbox'),
        $content = $lightbox.find('.content'),
        $caption = $lightbox.find('.caption span'),
        $previews,
        current, $strip,
        lbImage = template('<img id="preview{0}" src="{1}">'),
        lbVideo = template('<video id="preview{0}" src="{1}" ' +
                           'preload="auto" controls type="video/webm"> ' +
                           '</video>');
    if (!$lightbox.length) return;
    function showLightbox() {
        $previews = $(this).closest('.slider');
        $lightbox.show();
        showImage(this);
        $(window).bind('keydown.lightboxDismiss', function(e) {
            switch (e.which) {
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
        setTimeout(function() {
            $lightbox.addClass('show');
        }, 0);
    }
    function hideLightbox() {
        pauseVideo();
        $lightbox.removeClass('show');
        // We can't trust transitionend to fire in all cases.
        setTimeout(function() {
            $lightbox.hide();
        }, 500);
        $(window).unbind('keydown.lightboxDismiss');
    }
    function cookieCutter(values) {
        if (values[1].indexOf('.webm') > 0) {
            return lbVideo(values);
        } else {
            return lbImage(values);
        }
    }
    function pauseVideo() {
        var $video = $content.find('video:visible');
        if ($video.length) {
            $video.blur();
            $video[0].pause();
        }
    }
    function showImage(a) {
        var $a = $(a),
            $oldimg = $lightbox.find('img, video');
        current = $a.parent().index();
        $strip = $a.closest('ul').find('li');
        $previews.find('.panel').removeClass('active')
                 .eq(current).addClass('active');
        var $img = $('#preview'+current);
        if ($img.length) {
            $oldimg.removeClass('show');
            $img.addClass('show');
            $img.filter('video').focus();
        } else {
            console.log('no match found!', '#preview'+current, $img);
            $img = $(cookieCutter([current, $a.attr('href')]));
            $content.append($img);
            $img.bind('load loadstart', function(e) {
                $oldimg.removeClass('show');
                $img.addClass('show');
            });
        }
        $caption.text($a.attr('title'))
                .removeAttr('style oldtext')
                .truncate({dir: 'v'});
        $lightbox.find('.control').removeClass('disabled');
        if (current < 1) {
            $lightbox.find('.control.prev').addClass('disabled');
        }
        if (current == $strip.length-1) {
            $lightbox.find('.control.next').addClass('disabled');
        }
    }
    function showNext() {
        if (current < $strip.length-1) {
            showImage($strip.eq(current + 1).find('a'));
            pauseVideo();
            if (!this.window) {
                $(this).blur();
            }
        }
    }
    function showPrev() {
        if (current > 0) {
            showImage($strip.eq(current - 1).find('a'));
            pauseVideo();
            if (!this.window) {
                $(this).blur();
            }
        }
    }
    $lightbox.find('.next').click(_pd(showNext));
    $lightbox.find('.prev').click(_pd(showPrev));
    $lightbox.find('.close').click(_pd(function(e) {
        hideLightbox();
    }));
    z.page.on('click', '.tray ul a', _pd(showLightbox));
    $lightbox.click(function(e) {
        if ($(e.target).parent('#page').length) {
            hideLightbox();
        }
    });
})();
