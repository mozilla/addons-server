(function() {
    z.page.on('fragmentloaded', function() {
        var $abuse = $('#abuse');
        if ($abuse.find('form legend a').length) {
            var $ol = $abuse.find('ol');
            $ol.hide();
        }
        var RecaptchaOptions = {theme: 'custom'};
        z.page.on('click', '#recaptcha_different', _pd(function() {
            Recaptcha.reload();
        })).on('click', '#recaptcha_audio', _pd(function() {
            Recaptcha.switch_type('audio');
        }));
    });
})();
