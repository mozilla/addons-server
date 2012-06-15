(function() {
    z.page.on('fragmentloaded', function() {
        setTimeout(function() {
            // Make sure the class got updated.
            if (!$('body.reviews').length) {
                return;
            }

            initCharCount();

            // Hijack <select> with stars.
            $('select[name="rating"]').ratingwidget();

            // Handle review deletions.
            $('.delete').on('click', _pd(function() {
                var $this = $(this),
                    $r = $this.closest('.review');
                $r.addClass('deleting');
                $.post($this.attr('href')).success(function() {
                    $r.addClass('deleted');
                });
            }));

            // Toggle rating breakdown.
            var $breakdown = $('.grouped-ratings');
            $('.average-rating').on('click', _pd(function() {
                $breakdown.toggle();
            }));
            $breakdown.on('click', _pd(function() {
                $breakdown.hide();
            }));
        }, 0);
    });
})();
