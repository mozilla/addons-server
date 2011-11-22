// We don't want to wait for ready.
if ($('.login .browserid').length) {
    $('#show-normal-login').click(_pd(function(e) {
        $('#browserid-login').hide();
        $('.user-message').hide();
        $('#normal-login').show();
        $('#id_username').focus();
        $(window).trigger('resize');
    }));
}

// The `autofocus` attribute is wonky, so we do this.
$('.login #id_username:visible').focus();
