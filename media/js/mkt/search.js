(function() {
    // Because bug 673873 kills me.
    $('input[placeholder]').on('focus', function() {
        var $this = $(this);
        $this.data('placeholder', $this.attr('placeholder'))
             .removeAttr('placeholder');
    }).on('blur', function() {
        var $this = $(this);
        $this.attr('placeholder', $this.data('placeholder'));
    });

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
    }).on('click', '#search-listing .items', function(e) {
        // Let's treat each li as a click area for its data-href.
        var $target = $(e.target),
            url = $target.closest('.item').data().href;

        if (!$target.hasClass('button')) {
            window.location.href = url;
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
                $(window).trigger('loadfragment', href);
            }
        }
    }
    $(document).keyup(_.throttle(turnPages, 300));
})();
