z.page.on('fragmentloaded', function() {
    if ($('#recaptcha_div').length) {
        var recaptcha = $('body').data('recaptcha');
        if (recaptcha) {
            Recaptcha.create(recaptcha, 'recaptcha_div', {
                tabindex: 1,
                theme: 'red',
                callback: Recaptcha.focus_response_field
            });
        }
    }
});
