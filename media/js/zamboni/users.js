// Hijack "Admin / Editor Log in" context menuitem.
$('#admin-login').click(function() {
    window.location = $(this).attr('data-url');
});


// Recaptcha
function reloadReCaptchaOnClick(e) {
    e.preventDefault();
    Recaptcha.reload();
}

function reCaptchaSwitchClosure(type) {
    return function (e) {
        e.preventDefault();
        Recaptcha.switch_type(type);
    }
}

var RecaptchaOptions = { theme : 'custom' };

$('#recaptcha_different_text').click(reloadReCaptchaOnClick);
$('#recaptcha_different_audio').click(reloadReCaptchaOnClick);

$('#recaptcha_audio').click(reCaptchaSwitchClosure('audio'));
$('#recaptcha_text').click(reCaptchaSwitchClosure('image'));

$('#recaptcha_help').click(function(e) {
    e.preventDefault();
    Recaptcha.showhelp();
});
