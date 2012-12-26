define('login', ['notification'], function(notification) {

    var requestedLogin = false;

    $(window).bind('login', function() {
        $('#login').addClass('show');
    }).on('click', '.browserid', function(e) {
        var $this = $(this);
        $this.addClass('loading-submit');
        requestedLogin = true;
        navigator.id.request({
            termsOfService: '/terms-of-use',
            privacyPolicy: '/privacy-policy',
            oncancel: function() {
                $this.removeClass('loading-submit').blur();
            }
        });
        e.preventDefault();
    });
    z.body.on('click', '.logout', function() {
        // NOTE: Real logout operations happen on the action of the Logout
        // link/button. This just tells Persona to clean up its data.
        if (navigator.id) {
            navigator.id.logout();
        }
    });
    function gotVerifiedEmail(assertion) {
        if (assertion) {
            $.ajax({
                url: $('body').data('login-url'),
                type: 'POST',
                data: {'assertion': assertion},
                success: finishLogin,
                error: function(jqXHR, textStatus, error) {
                    // ask for additional credential info.
                    var err = {msg: jqXHR.responseText};
                    if (!err.msg) {
                        err.msg = gettext("BrowserID login failed. Maybe you don't have an account under that email address?") + " " + textStatus + " " + error;
                    }
                    z.page.trigger('notify', {msg: $(err.msg).text()});
                    $.Deferred().reject(err);
                }
            })
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
                }).then(function() {
                    window.location.reload();
                });
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
            onlogin: function(assert) {
                gotVerifiedEmail(assert);
            },
            onlogout: function() {
            }
        });
    }

    // Load `include.js` from persona.org, and drop login hotness like it's hot.
    var s = document.createElement('script');
    s.src = z.body.data('persona-url');
    document.body.appendChild(s);
    s.onload = init_persona;
    $('.browserid').css('cursor', 'wait');

});
