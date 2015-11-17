(function() {
    function getClient() {
        return new FxaRelierClient(config.clientId, {
        contentHost: config.contentHost,
        oauthHost: config.oauthHost,
        });
    }

    var fxaConfig = {
        "http://olympia.dev": {
            "clientId": "cd5a21fafacc4744",
            "contentHost": "https://stable.dev.lcip.org",
            "loginUri": "http://olympia.dev/api/v3/login/",
            "oauthHost": "https://oauth-stable.dev.lcip.org/v1",
            "redirectUri": "http://olympia.dev/fxa-authorize",
            "scope": "profile",
        },
        "http://localhost:8000": {
            "clientId": "a1dc6167e57ad856",
            "contentHost": "https://stable.dev.lcip.org",
            "loginUri": "http://olympia.dev/api/v3/login/",
            "oauthHost": "https://oauth-stable.dev.lcip.org/v1",
            "redirectUri": "http://localhost:8000/fxa-authorize",
            "scope": "profile",
        },
    };
    var config = fxaConfig[location.origin];
    if (!config) {
        console.log("[FxA] No FxA config found for " + location.origin);
    }
    var fxaClient = getClient();

    window.fxaLogin = function() {
        console.log('[FxA] Starting sign in');
        return fxaClient.auth.signIn({
            ui: 'lightbox',
            state: 'foo',
            redirectUri: config.redirectUri,
            scope: config.scope,
        });
    };

    $('body').on('click', '.fxa-login', function(e) {
        e.preventDefault();

        fxaLogin().then(function(response) {
            console.log('[FxA] Login success', response);
            var headers = new Headers();
            $.post(config.loginUri, {
                action: response.action,
                code: response.code,
                state: response.state,
                client_id: config.clientId,
            }).then(function(response) {
                console.log('[FxA] Server login response', response);
                window.location.reload();
            });
        }, function() {
            console.log('[FxA] Login failed', arguments);
        });
    });
})();
