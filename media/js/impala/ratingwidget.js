// Replaces rating selectboxes with the rating widget
$.fn.ratingwidget = function() {
    this.each(function(n, el) {
        var $el = $(el),
            $widget = $("<span class='ratingwidget stars stars-0'></span>"),
            rs = [],
            showStars = function(n) {
                $widget.removeClass('stars-0 stars-1 stars-2 stars-3 stars-4 stars-5').addClass('stars-' + n);
            };
        for (var i=1; i<=5; i++) {
            rs.push("<label data-stars='", i, "'>",
                    format(ngettext('{0} star', '{0} stars', i), [i]),
                    "<input type='radio' name='rating' value='", i, "'></label>");
        }
        var rating = 0;
        $widget.click(function(evt) {
            var t = $(evt.target);
            if (t.val()) {
                showStars(t.val());
            }
            rating = t.val();
        });
        $widget.mouseover(function(evt) {
            var t = $(evt.target);
            if (t.attr('data-stars')) {
                showStars(t.attr('data-stars'));
            }
        });
        $widget.mouseout(function(evt) {
            showStars(rating);
        });
        $widget.html(rs.join(''));
        $el.before($widget);
        $el.detach();
    });
    return this;
}
