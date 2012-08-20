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
    });

    var expandListings = false;
    var $expandToggle = $('#site-header .expand');

    // Toggle app listing graphical/compact view.
    $expandToggle.click(_pd(function(e) {
        expandListings = !expandListings;
        setTrays(expandListings);
    }));

    z.page.on('fragmentloaded', function() {
        if (z.body.data('page-type') === 'search') {
            expandListings = localStorage.getItem('expand-listings') === 'true';
            if (expandListings) {
                setTrays(true);
            }
        }
    });


    function setTrays(expanded) {
        $('ol.listing').toggleClass('expanded', expanded);
        $expandToggle.toggleClass('active', expanded);
        localStorage.setItem('expand-listings', expanded);
        if (expanded) {
            z.page.trigger('populatetray');
        }
    }


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
