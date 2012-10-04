(function() {

    // Add 'sel' class to active filter and set hidden input value.
    z.page.on('click', '#filters .toggles a', function() {
        selectMe($(this));
        return false;
    });

    // Clear search field on 'cancel' search suggestions.
    $('#site-header').on('click', '.header-button.cancel', _pd(function() {
        $('#site-search-suggestions').trigger('dismiss');
        $('#search-q').val('');
    }));

    function selectMe($elm) {
        var $myUL = $elm.closest('ul'),
            val = '',
            vars = z.getVars($elm[0].search);

        if ($elm.hasClass('cancel')) {
            return;
        }
        $myUL.find('a').removeClass('sel');


        if ($myUL[0].id == 'filter-prices') {
            val = vars.price || '';
        } else if ($myUL[0].id == 'filter-sort') {
            val = vars.sort || '';
        }
        $myUL.find('+ input[type=hidden]').val(val);
        $elm.addClass('sel');
    }

    $(document).on('click', '#filters', function(e) {
        if ($(e.target).parent('#page').length) {
            $('#filters').removeClass('show');
        }
    });

    // Apply filters button.
    z.page.on('click', '#filters .apply', _pd(function() {
        $('#filters form').submit();
    }));

    // If we're on desktop, show graphical results - unless specified by user.
    var expandListingsStored, expandListings;

    var $expandToggle = $('#site-header .expand');

    // Toggle app listing graphical/compact view.
    $expandToggle.click(_pd(function(e) {
        expandListingsStored = localStorage.getItem('expand-listings');
        expandListings = expandListingsStored ? expandListingsStored === 'true' : z.capabilities.desktop;

        expandListings = !expandListings;
        setTrays(expandListings);
    }));

    z.page.on('fragmentloaded', function() {
        if (z.body.data('page-type') === 'search') {
            expandListingsStored = localStorage.getItem('expand-listings');
            expandListings = expandListingsStored ? expandListingsStored === 'true' : z.capabilities.desktop;

            setTrays(expandListings);
        }

        // Set "Category Name" or "Apps" as search placeholder.
        var $q = $('#search-q');
        $q.attr('placeholder', z.context.category || $q.data('placeholder-default'));
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
