(function() {
    var config = $('body').data('fxa-config');
    var fxaClient = new FxaRelierClient(config.clientId, {
        contentHost: config.contentHost,
        oauthHost: config.oauthHost,
    });

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
            state: 'foo',
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
