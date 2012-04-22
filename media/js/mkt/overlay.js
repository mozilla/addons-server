(function() {
    function dismiss() {
        $('.overlay.show').removeClass('show');
        $(window).trigger('overlay_dismissed');
    }
    z.page.on('fragmentloaded', function(e) {
        // Dismiss overlay when we load a new fragment.
        dismiss();

        // Dismiss overlay when we click outside of it.
        $('.overlay').on('click', function(e) {
            if ($(e.target).parent('body').length) {
                dismiss();
            }
        });

        // Dismiss overlay when we press escape.
        $(window).bind('keydown.overlayDismiss', function(e) {
            if (!fieldFocused(e) && e.which == z.keys.ESCAPE) {
                e.preventDefault();
                dismiss();
            }
        });
    });
})();
