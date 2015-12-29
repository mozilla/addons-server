(function() {
    var config = $('body').data('fxa-config');
    var fxaClient = new FxaRelierClient(config.clientId, {
        contentHost: config.contentHost,
        oauthHost: config.oauthHost,
    });

    function currentPath() {
        return location.pathname + location.search + location.hash;
    }

    function urlsafe(str) {
        // This function makes a base64 string URL safe using python's base64
        // module's replacements.
        // https://docs.python.org/2/library/base64.html#base64.urlsafe_b64encode
        return str.replace(new RegExp('[+/=]', 'g'), function(match) {
            switch (match) {
                case '+':
                    return '-';
                case '/':
                    return '_';
                case '=':
                    return '';
                default:
                    return match;
            }
        });
    }

    function fxaLogin(opts) {
        function postConfig(response) {
            return {
                action: response.action,
                code: response.code,
                state: response.state,
                client_id: config.clientId,
            };
        }

        opts = opts || {};
        var authConfig = {
            state: config.state + ':' + urlsafe(btoa(currentPath())),
            redirectUri: config.redirectUrl,
            scope: config.scope,
        };
        if (opts.signUp) {
            console.log('[FxA] Starting register');
            return fxaClient.auth.signUp(authConfig);
        } else {
            console.log('[FxA] Starting login');
            return fxaClient.auth.signIn(authConfig);
        }
    }

    $('body').on('click', '.fxa-login', function(e) {
        e.preventDefault();
        fxaLogin();
    }).on('click', '.fxa-register', function(e) {
        e.preventDefault();
        fxaLogin({signUp: true});
    });
})();
