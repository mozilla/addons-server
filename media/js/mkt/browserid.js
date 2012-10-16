_.extend(z, (function() {
    var loginUrl = $('body').data('login-url'),
        exports = {},
        $def,
        to;

    exports.login = function(go_to) {
        $def = $.Deferred();
        to = go_to;

        navigator.id.get(gotVerifiedEmail, {
            privacyURL: 'https://marketplace.mozilla.org/en-US/privacy-policy',
            tosURL: 'https://marketplace.mozilla.org/en-US/terms-of-use'
        });

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
        } else {
          // user clicked 'cancel', don't do anything
          $('.loading-submit').removeClass('loading-submit');
        }
    }

    function finishLogin() {
        $def.resolve();
        // If we have a `to` query string and it's not outbound, go "to" it.
        to = to || z.getVars(window.location.search).to;
        if (to && to[0] == '/') {
            window.location = to;
        } else {
            window.location.reload();
        }
    }

    return exports;
})());
