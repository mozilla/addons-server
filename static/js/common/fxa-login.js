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
            ui: 'lightbox',
            state: 'foo',
            redirectUri: config.redirectUrl,
            scope: config.scope,
        };
        if (opts.signUp) {
            console.log('[FxA] Starting register');
            return fxaClient.auth.signUp(authConfig).then(function(response) {
                console.log('[FxA] Register success', response);
                return $.post(config.registerUrl, postConfig(response));
            });
        } else {
            console.log('[FxA] Starting login');
            return fxaClient.auth.signIn(authConfig).then(function(response) {
                console.log('[FxA] Login success', response);
                return $.post(config.loginUrl, postConfig(response));
            });
        }
    }

    $('body').on('click', '.fxa-login', function(e) {
        e.preventDefault();

        fxaLogin().then(function(response) {
            console.log('[FxA] Server login response', response);
            window.location.reload();
        }, function(error) {
            console.log('[FxA] Login failed', error);
        });
    }).on('click', '.fxa-register', function(e) {
        e.preventDefault();

        fxaLogin({signUp: true}).then(function(response) {
            console.log('[FxA] Server register response', response);
            window.location.reload();
        }, function(error) {
            console.log('[FxA] Register failed', error);
        });
    });
})();
