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

    // Add 'sel' class to active filter and set hidden input value.
    z.page.on('click', '#filters .toggles a', function() {
        selectMe($(this));
        return false;
    });


    function selectMe($elm) {
        var $myUL = $elm.closest('.toggles'),
            val = '',
            vars = z.getVars($elm[0].search);

        $myUL.find('a').removeClass('sel');

        if ($myUL[0].id == 'filter-prices') {
            val = vars.price || '';
        } else if ($myUL[0].id == 'filter-categories') {
            val = vars.cat || '';
        } else if ($myUL[0].id == 'filter-sort') {
            val = vars.sort || '';
        }
        $myUL.find('input[type=hidden]').val(val);
        $elm.addClass('sel');
    }

    // Apply filters button.
    z.page.on('click', '#filters .header-button.apply', _pd(function() {
        $('#filters form').submit();
    }));

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
