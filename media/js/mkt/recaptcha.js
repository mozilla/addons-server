z.page.on('fragmentloaded', function() {
    if ($('#recaptcha_div').length) {
        var recaptcha = $('body').data('recaptcha');
        if (recaptcha) {
            Recaptcha.create(recaptcha, 'recaptcha_div', {
                tabindex: 1,
                theme: 'red'
            });
            var RecaptchaOptions = {theme: 'custom'};
            z.page.on('click', '#recaptcha_different', _pd(function() {
                Recaptcha.reload();
            })).on('click', '#recaptcha_audio', _pd(function() {
                Recaptcha.switch_type('audio');
            })).on('click', '#recaptcha_help', _pd(function() {
                Recaptcha.showhelp();
            }));
        }
    }
});
