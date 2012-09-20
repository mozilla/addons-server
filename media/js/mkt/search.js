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
    }).on('click', '#filters .confirm-action a', function() {
        var $this = $(this);
        selectMe($this);
        $this.closest('.confirm-action').removeClass('show');
        $('.picker').toggleClass('sel');
        return false;
    });


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
        } else if ($myUL[0].id == 'filter-categories') {
            val = vars.cat || '';
            $('.picker').text($elm.text());
        } else if ($myUL[0].id == 'filter-sort') {
            val = vars.sort || '';
        }
        $myUL.find('+ input[type=hidden]').val(val);
        $elm.addClass('sel');
    }

    // Apply filters button.
    z.page.on('click', '#filters .apply', _pd(function() {
        $('#filters form').submit();
    })).on('click', '#filters .picker', _pd(function() {
        $('#filter-categories').addClass('show');
        if ($('#filter-categories li').length > z.confirmBreakNum) {
            $('#filter-categories').addClass('two-col');
        } else {
            $('#filter-categories').removeClass('two-col');
        }
        $(this).toggleClass('sel');
    })).on('click', '.confirm-action .cancel', _pd(function(e) {
        $(e.target).closest('.confirm-action').removeClass('show');
    }));

    var expandListings = localStorage.getItem('expand-listings') === 'true';
    var $expandToggle = $('#site-header .expand');

    // Toggle app listing graphical/compact view.
    $expandToggle.click(_pd(function(e) {
        expandListings = !expandListings;
        setTrays(expandListings);
    }));

    z.page.on('fragmentloaded', function() {
        if (z.body.data('page-type') === 'search') {
            setTrays(expandListings);
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
