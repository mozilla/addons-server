enableFxALogin();

function enableFxALogin() {
    var loginPathRegex = new RegExp('^/[^/]+/[^/]+/users/login/?$');
    var config = $('body').data('fxa-config');

    function nextPath() {
        var to = new Uri(location).getQueryParamValue('to');
        if (to) {
            return to;
        } else if (!loginPathRegex.test(location.pathname)) {
            return location.pathname + location.search + location.hash;
        }
        return undefined;
    }

    function b64EncodeUnicode(str) {
        // This is from the MDN article about base 64 encoding.
        // https://developer.mozilla.org/en-US/docs/Web/API/WindowBase64/Base64_encoding_and_decoding#The_Unicode_Problem.
        return btoa(encodeURIComponent(str).replace(/%([0-9A-F]{2})/g, function(match, p1) {
            return String.fromCharCode('0x' + p1);
        }));
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
        var to = nextPath();
        var authConfig = {
            client_id: config.clientId,
            state: config.state,
            redirectUri: config.redirectUrl,
            scope: config.scope,
        };
        if (to) {
          authConfig.state += ':' + urlsafe(b64EncodeUnicode(to));
        }
        if (opts.email || config.email) {
            authConfig.email = opts.email || config.email;
        }
        if (opts.migration) {
            authConfig.migration = 'amo';
        }
        var url = config.oauthHost + '/authorization?' + $.param(authConfig);
        console.log('[FxA] Starting login', url);
        location.href = url;
    }

    $('body').on('click', '.fxa-login', function(e) {
        e.preventDefault();
        fxaLogin({migration: true});
    });

    function showLoginForm($form) {
        $form.removeClass('login-source-form')
             .addClass('login-form');
        $form.find('[name="password"]').prop('required', true).focus();
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
}
