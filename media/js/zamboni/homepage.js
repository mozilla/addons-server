$(document).ready(function(){
    if (!$(document.body).hasClass('home')) {
        return;
    }

    $('#homepage .listing-header a').click(function(e) {
        e.preventDefault();
        update(this, true);
    });

    // Switch to the tab of the <a> given as `link`.
    // Only call pushState if `push` is True.
    function update(link, push) {
        var target = $(link).attr('data-target');

        // Change the list to show the right add-ons.
        $('.addon-listing').attr('class', 'addon-listing addon-listing-' + target);

        // Update the selected tab.
        $('.listing-header .selected').removeClass('selected');
        $('#' + target).addClass('selected').focus();

        if (push && history.pushState) {
            history.pushState({target: target}, document.title, link.href);
        }
    };

    // If we already have a hash, switch to the tab.
    if (location.hash) {
        var selected = $('#homepage .listing-header ' + location.hash);
        if (selected) {
            selected.find('a').click().focus();
        }
    } else {
        // Add the current page to the history so we can get back.
        var selected = $('#homepage .listing-header .selected a')[0];
        update(selected, true, true);
    }

    // Set up our history callback.
    $(window).bind('popstate', function(ev) {
        // We don't pushState here because we'd be stuck in this position.
        var e = ev.originalEvent;
        if (e.state && e.state.target) {
            var a = $('#' + e.state.target + ' a')[0];
            update(a, false);
        }
    });
});
