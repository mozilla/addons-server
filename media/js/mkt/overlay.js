(function() {
    z.page.on('click', '.overlay.show', function(e) {
        // If we're clicking outside of the overlay, dismiss it.
        if ($(e.target).parent('body').length) {
            $(this).removeClass('show');
            $(window).trigger('overlay_dismissed');
        }
    }).on('fragmentloaded', function(e) {
        $('.overlay.show').removeClass('show');
        $(window).trigger('overlay_dismissed');
    });
})();
