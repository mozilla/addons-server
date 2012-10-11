(function() {

    z.page.on('click', 'b[data-href]', _pd(function(e) {
        e.stopPropagation();
        window.location = $(this).attr('data-href');
    }));

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
    var expandListings;

    var $expandToggle = $('#site-header .expand');

    // Toggle app listing graphical/compact view.
    $expandToggle.click(_pd(function(e) {
        expandListings = !expandListings;
        setTrays(expandListings);
    }));

    z.page.on('fragmentloaded', function() {
        if (z.body.data('page-type') === 'search') {
            initExpanded();
            setTrays(expandListings);
        }

        // Set "Category Name" or "Apps" as search placeholder.
        var $q = $('#search-q');
        $q.attr('placeholder', z.context.category || $q.data('placeholder-default'));
    });

    function initExpanded() {
        var storedExpand = localStorage.getItem('expand-listings');
        if (storedExpand === undefined) {
            expandListings = z.capabilities.desktop
        } else {
            expandListings = storedExpand === 'true';
        }
    }

    initExpanded();

    function setTrays(expanded) {
        $('ol.listing').toggleClass('expanded', expanded);
        $expandToggle.toggleClass('active', expanded);
        localStorage.setItem('expand-listings', expanded);
        if (expanded) {
            z.page.trigger('populatetray');
        }
    }

})();
