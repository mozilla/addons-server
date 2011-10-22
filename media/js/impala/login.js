// we don't want to wait for ready.
if ($('.login .browserid').length) {
    $('#show-normal-login').click(_pd(function(e) {
        $('.user-message').hide();
        $('#normal-login').show();
        $('#id_username').focus();
    }));
}