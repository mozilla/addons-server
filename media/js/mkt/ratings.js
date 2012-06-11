(function() {
    z.page.on('fragmentloaded', function() {
        if (!$('#submit-review').length) {
            return;
        }
        initCharCount();

        // Hijack <select> with Thumbs Up and Thumbs Down.
        $('select[name="rating"]').ratingwidget();
    });
})();
