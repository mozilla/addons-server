(function() {
    var config = $('body').data('fxa-config');
    var fxaClient = new FxaRelierClient(config.clientId, {
        contentHost: config.contentHost,
        oauthHost: config.oauthHost,
    });

    function nextPath() {
        var to = new Uri(location).getQueryParamValue('to');
        if (to) {
            return to;
        } else {
            return location.pathname + location.search + location.hash;
        }
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
        opts = opts || {};
        var authConfig = {
            email: opts.email,
            state: config.state + ':' + urlsafe(btoa(nextPath())),
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

    function showLoginForm($form) {
        $form.removeClass('login-source-form')
             .addClass('login-form');
        $form.find('[name="password"]').prop('required', true);
    }

    function showLoginSourceForm($form) {
        $form.addClass('login-source-form')
             .removeClass('login-form');
        $form.find('[name="password"]').removeAttr('required');
    }

    $('body').on('submit', '.login-source-form', function(e) {
        e.preventDefault();
        var $form = $(this);
        var email = $form.find('input[name="username"]').val();
        $.get('/api/v3/accounts/source/', {email: email}).then(function(data) {
            if (data.source === 'amo') {
                showLoginForm($form);
            } else {
                fxaLogin({email: email});
            }
        });
    }).on('input', '.login-form input[name="username"]', function(e) {
        showLoginSourceForm($('.login-form'));
    });

    $(function() {
        var $form = $('.login-source-form');
        if ($form.length > 0) {
            showLoginSourceForm($form);
        }
    });
})();
