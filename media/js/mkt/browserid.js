_.extend(z, (function() {
    var loginUrl = $('body').data('login-url'),
        exports = {},
        $def;

    exports.login = function() {
        $def = $.Deferred();

        navigator.id.getVerifiedEmail(gotVerifiedEmail);

        return $def;
    };

    function gotVerifiedEmail(assertion) {
        if (assertion) {
            $.ajax({
                url: loginUrl,
                type: 'POST',
                data: {
                    'assertion': assertion
                },
                success: finishLogin,
                error: function(jqXHR, textStatus, errorThrown) {
                    var err = {};
                    if (jqXHR.status == 400) {
                        err.msg = "bad admin";
                        err.privs = true;
                    } else {
                        err.msg = jqXHR.responseText;
                        if (!err.msg) {
                            err.msg = gettext("BrowserID login failed. Maybe you don't have an account under that email address?") +
                                          " " + textStatus + " " + errorThrown;
                        }
                    }
                    $def.reject(err);
                }
            });
        }
    }

    function finishLogin() {
        $def.resolve();
        window.location.reload();
    }

    return exports;
})());
