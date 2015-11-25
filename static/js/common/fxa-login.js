(function() {
    var config = $('body').data('fxa-config');
    var fxaClient = new FxaRelierClient(config.clientId, {
        contentHost: config.contentHost,
        oauthHost: config.oauthHost,
    });

    function fxaLogin() {
        console.log('[FxA] Starting sign in');
        return fxaClient.auth.signIn({
            ui: 'lightbox',
            state: 'foo',
            redirectUri: config.redirectUrl,
            scope: config.scope,
        });
    }

    $('body').on('click', '.fxa-login', function(e) {
        e.preventDefault();

        fxaLogin().then(function(response) {
            console.log('[FxA] Login success', response);
            var headers = new Headers();
            $.post(config.loginUrl, {
                action: response.action,
                code: response.code,
                state: response.state,
                client_id: config.clientId,
            }).then(function(response) {
                console.log('[FxA] Server login response', response);
                window.location.reload();
            }, function(error) {
                console.log('[FxA] Server login error', error);
                alert('There was an error logging you in');
            });
        }, function() {
            console.log('[FxA] Login failed', arguments);
        });
    });
})();
