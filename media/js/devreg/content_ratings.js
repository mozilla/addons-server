/* IARC content ratings. */
define('iarc-ratings', [], function() {

    // Poll to see if IARC rating process finished.
    $createRating = $('.create-rating');
    $('input[type=submit]', $createRating).on('click', function() {
        var $this = $(this);
        $createRating.addClass('loading');
        var apiUrl = $this.data('api-url');
        var redirectUrl = $this.data('redirect-url');

        setInterval(function() {
            $.get(apiUrl, function(data) {
                if (!('objects' in data)) {
                    $('.error').show();
                    $createRating.removeClass('loading');
                } else if (data.objects.length) {
                    // Redirect to summary page.
                    window.location = redirectUrl;
                    $('.done').show();
                    $createRating.removeClass('loading');
                }
            });
        }, 2000);
    });
});

require('iarc-ratings');
