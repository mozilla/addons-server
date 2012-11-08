z.page.on('fragmentloaded', function() {
    if ($('#recaptcha_image').length) {
        var recaptcha = $('body').data('recaptcha');
        if (recaptcha) {
            z.page.on('click', '#recaptcha_different_text', _pd(function() {
                Recaptcha.reload();
            })).on('click', '#recaptcha_different_audio', _pd(function() {
                Recaptcha.reload();
            })).on('click', '#recaptcha_text', _pd(function() {
                Recaptcha.switch_type('image');
            })).on('click', '#recaptcha_audio', _pd(function() {
                Recaptcha.switch_type('audio');
            })).on('click', '#recaptcha_help', _pd(function() {
                Recaptcha.showhelp();
            }));
        }
    }
});
