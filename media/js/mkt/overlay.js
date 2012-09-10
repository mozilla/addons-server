(function() {
    z.body.on('touchmove', '.overlay', function(e){
        e.preventDefault();
        e.stopPropagation();
    });

    function dismiss() {
        var $overlay = $('.overlay.show');
        if ($overlay.length) {
            $overlay.removeClass('show');
            $(window).trigger('overlay_dismissed');
        }
    }

    z.page.on('fragmentloaded', function(e) {
        // Dismiss overlay when we load a new fragment.
        dismiss();
    });

    // Dismiss overlay when we click outside of it.
    $(document).on('click', '.overlay', function(e) {
        if ($(e.target).parent('body').length) {
            dismiss();
        }
    });

    // Dismiss overlay when we press escape.
    $(window).on('keydown.overlayDismiss', function(e) {
        if (!fieldFocused(e) && e.which == z.keys.ESCAPE) {
            e.preventDefault();
            dismiss();
        }
    });
})();
