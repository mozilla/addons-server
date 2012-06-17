// Replaces rating selectboxes with the rating widget
$.fn.ratingwidget = function() {
    this.each(function(n, el) {
        var $el = $(el),
            $widget = $("<span class='ratingwidget stars stars-0'></span>"),
            rs = '',
            showStars = function(n) {
                $widget.removeClass('stars-0 stars-1 stars-2 stars-3 stars-4 stars-5').addClass('stars-' + n);
            },
            setStars = function(n) {
                if (rating == n) return;
                var e = $widget.find(format('[value="{0}"]', n));
                e.click();
                showStars(n);
                rating = n;
            };
        for (var i=1; i<=5; i++) {
            rs += ('<label data-stars="' + i + '">' +
                   format(ngettext('{0} star', '{0} stars', i), [i]) +
                   '<input type="radio" name="rating" value="' + i + '"></label>');
        }
        var rating = 0;
        // Existing rating found so initialize the widget.
        if ($('option[selected]', $el).length) {
            rating = $el.val();
            showStars(rating);
        }
        $widget.on('click', function(evt) {
            var t = $(evt.target);
            if (t.val()) {
                showStars(t.val());
            }
            rating = t.val();
        }).on('mouseover', function(evt) {
            var t = $(evt.target);
            if (t.attr('data-stars')) {
                showStars(t.attr('data-stars'));
            }
        }).mouseout(function(evt) {
            showStars(rating);
        }).on('touchmove touchend', function(e) {
            var wid = $widget.width();
            var left = $widget.offset().left;
            var r = (e.originalEvent.touches[0].clientX - left) / wid * 5 + 1;
            r = ~~Math.min(Math.max(r,1),5);
            setStars(r);
        });
        $widget.html(rs);
        $el.before($widget).detach();
    });
    return this;
};
