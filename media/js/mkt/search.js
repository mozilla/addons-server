(function() {
    z.page.on('click', '#search-facets li.facet', function(e) {
        var $this = $(this);
        if ($this.hasClass('active')) {
            if ($(e.target).is('a')) {
                return;
            }
            $this.removeClass('active');
        } else {
            $this.closest('ul').removeClass('active');
            $this.addClass('active');
        }
    });
    function turnPages(e) {
        if (fieldFocused(e)) {
            return;
        }
        if (e.which == z.keys.LEFT || e.which == z.keys.RIGHT) {
            var sel;
            if (e.which == z.keys.LEFT) {
                sel = '.paginator .prev:not(.disabled)';
            } else {
                sel = '.paginator .next:not(.disabled)';
            }
            var href = $(sel).attr('href');
            if (href) {
                e.preventDefault();
                z.fetchFragment(href);
            }
        }
    }
    $(document).keyup(_.throttle(turnPages, 300));
})();
