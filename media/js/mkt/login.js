define('login', ['notification'], function(notification) {

    var requestedLogin = false;

    z.doc.bind('login', function(skipDialog) {
        if (skipDialog) {
            startLogin();
        } else {
            $('.overlay.login').addClass('show');
        }
    }).on('click', '.browserid', function(e) {
        var $this = $(this);
        $this.addClass('loading-submit');
        z.doc.on('logincancel', function() {
            $this.removeClass('loading-submit').blur();
        })
        startLogin();
        e.preventDefault();
    });

    function startLogin() {
        requestedLogin = true;
        navigator.id.request({
            forceIssuer: z.body.data('persona-unverified-issuer') || null,
            allowUnverified: true,
            termsOfService: '/terms-of-use',
            privacyPolicy: '/privacy-policy',
            oncancel: function() {
                z.doc.trigger('logincancel');
            }
        });
    }

    z.body.on('click', '.logout', function() {
        // NOTE: Real logout operations happen on the action of the Logout
        // link/button. This just tells Persona to clean up its data.
        if (navigator.id) {
            navigator.id.logout();
        }
    });
    function gotVerifiedEmail(assertion) {
        if (assertion) {
            var data = {assertion: assertion};
            // When id._shimmed is false we know that Persona is
            // native on the device. Even though this seems fragile
            // it is well supported by Persona (for now).
            data.is_native = navigator.id._shimmed ? 0 : 1;

            $.post(z.body.data('login-url'), data)
             .success(finishLogin)
             .error(function(jqXHR, textStatus, error) {
                var err = jqXHR.responseText;
                if (!err) {
                    err = gettext("Persona login failed. Maybe you don't have an account under that email address?") + " " + textStatus + " " + error;
                }
                // Catch-all for XHR errors otherwise we'll trigger 'notify'
                // with its message as one of the error templates.
                if (jqXHR.status != 200) {
                    err = gettext('Persona login failed. A server error was encountered.');
                }
                z.page.trigger('notify', {msg: err});
             });
        } else {
            $('.loading-submit').removeClass('loading-submit');
        }
    }

    function finishLogin() {
        var to = z.getVars().to;
        if (to && to[0] == '/') {
            // Browsers may helpfully add "http:" to URIs that begin with double
            // slashes. This converts instances of double slashes to single to
            // avoid other helpfullness. It's a bit of extra paranoia.
            to = decodeURIComponent(to.replace(/\/*/, '/'));
            // Convert a local URI to a fully qualified local URL.
            window.location = window.location.protocol + '//'  +
                window.location.host + to;
        } else {
            console.log('finished login');
            if (requestedLogin) {
                window.location.reload();
            } else {
                notification({
                    message: gettext('Successfully signed in. Click here to reload.')
                }).then(window.location.reload);
            }
        }
    }

    function init_persona() {
        $('.browserid').css('cursor', 'pointer');
        var user = z.body.data('user');
        var email = user ? user.email : '';
        console.log('detected user', email);
        navigator.id.watch({
            loggedInUser: email,
            onlogin: gotVerifiedEmail,
            onlogout: function() {}
        });
    }

    // Load `include.js` from persona.org, and drop login hotness like it's hot.
    var s = document.createElement('script');
    s.onload = init_persona;
    if (z.capabilities.firefoxOS) {
        // Load the Firefox OS include that knows how to handle native Persona.
        // Once this functionality lands in the normal include we can stop
        // doing this special case. See bug 821351.
        s.src = z.body.data('native-persona-url');
    } else {
        s.src = z.body.data('persona-url');
    }
    document.body.appendChild(s);
    $('.browserid').css('cursor', 'wait');

});
