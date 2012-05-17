(function() {
    z.page.on('fragmentloaded', function() {
        initCharCount();

        // Hijack <select> with Thumbs Up and Thumbs Down.
        if ($('#submit-rating').length) {
            var $up = $('#thumbs-up'),
                $down = $('#thumbs-down'),
                $score = $('#id_score'),
                $review = $('#id_body');

            function upRate() {
                $down.removeClass('voted');
                $up.toggleClass('voted');
            }
            function downRate() {
                $up.removeClass('voted');
                $down.toggleClass('voted');
            }

            $up.on('click', function() {
                upRate();
                $score.val($score.val() == '1' ? '' : '1');
                if (!$review.val()) {
                   $review.focus();
                }
            });
            $down.on('click', function() {
                downRate();
                $score.val($score.val() == '-1' ? '' : '-1');
                if (!$review.val()) {
                  $review.focus();
                }
            });

            // Initialize thumbs when POST'ed.
            if ($score.val() == '-1') {
                downRate();
            } else if ($score.val() == '1') {
                upRate();
            }
        }
    });
})();
