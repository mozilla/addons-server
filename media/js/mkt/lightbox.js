(function () {
    var $lightbox = $('#lightbox');
    var $section = $lightbox.find('section');
    var $content = $lightbox.find('.content');
    var currentApp;
    var previews;
    var slider;

    // prevent mouse cursors from dragging these images.
    $lightbox.on('dragstart', function(e) {
        e.preventDefault();
    });

    function showLightbox() {
        var which = $(this).closest('li').index();
        var $tray = $(this).closest('.tray');
        var $tile = $tray.prev();

        // we get the screenshots from the associated tile. No tile? bail.
        if (!$tile.hasClass('mkt-tile')) return;

        var product = $tile.data('product');
        var id = product.id;

        if (id != currentApp || !slider) {
            currentApp = id;
            previews = product.previews;
            renderPreviews();
        }

        // set up key bindings
        $(window).bind('keydown.lightboxDismiss', function(e) {
            switch (e.which) {
                case z.keys.ESCAPE:
                    e.preventDefault();
                    hideLightbox();
                    break;
                case z.keys.LEFT:
                    e.preventDefault();
                    if (slider) slider.toPrev();
                    break;
                case z.keys.RIGHT:
                    e.preventDefault();
                    if (slider) slider.toNext();
                    break;
            }
        });

        // fade that bad boy in
        $lightbox.show();
        setTimeout(function() {
            slider.moveToPoint(which);
            resize();
            $lightbox.addClass('show');
        }, 0);
    }

    function renderPreviews() {
        // clear out the existing content
        $content.empty();

        // place in a pane for each image/video with a 'loading' placeholder
        // and caption.
        _.each(previews, function(p) {
            var $el = $('<li class="loading">');
            var $cap = $('<div class="caption">');
            $cap.text(p.caption);
            $el.append($cap);
            $content.append($el);

            // let's fail elegantly when our images don't load.
            // videos on the other hand will always be injected.
            if (p.type == 'video/webm') {
                // we can check for `HTMLMediaElement.NETWORK_NO_SOURCE` on the
                // video's `networkState` property at some point.
                var v = $('<video src="' + p.fullUrl + '" controls></video>');
                $el.removeClass('loading');
                $el.append(v);
            } else {
                var i = new Image();

                i.onload = function() {
                    $el.removeClass('loading');
                    $el.append(i);
                };
                i.onerror = function() {
                    $el.removeClass('loading');
                    $el.append('<b class="err">&#x26A0;</b>');
                };

                // attempt to load the image.
                i.src = p.fullUrl;
            }
        });

        // $section doesn't have its proper width until after a paint.
        slider = Flipsnap($content[0]);
        slider.element.addEventListener('fsmoveend', pauseVideos, false);
    }

    // we need to adjust the scroll distances on resize.
    $(window).on('resize', _.debounce(resize, 200));

    function resize() {
        if (!slider) return;
        $content.find('.caption').lineclamp(2);
        slider.distance = $section.width();
        slider.refresh();
    }

    // if a tray thumbnail is clicked, load up our lightbox.
    z.page.on('click', '.tray ul a', _pd(showLightbox));


    // dismiss the lighbox when we click outside it or on the close button.
    $lightbox.click(function(e) {
        if ($(e.target).is('#lightbox')) {
            hideLightbox();
            e.preventDefault();
        }
    });
    $lightbox.find('.close').click(_pd(function(e) {
        hideLightbox();
    }));

    function pauseVideos() {
        $('video').each(function() {
            this.pause();
        });
    }

    function hideLightbox() {
        pauseVideos();
        $lightbox.removeClass('show');
        // We can't trust transitionend to fire in all cases.
        setTimeout(function() {
            $lightbox.hide();
        }, 500);
        $(window).unbind('keydown.lightboxDismiss');
    }

})();

