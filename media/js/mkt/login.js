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
    // Hijack the login form to send us to the right place
    $('#login form').submit(function(e) {
        e.stopPropagation();
        var $this = $(this),
            action = $this.attr('action') + format('?to={0}', window.location.pathname);
        $this.attr('action', action);
    });
    (function() {
        function logout() {
            $(".logout").bind('click', function(e) {
                // NOTE: Real logout operations happen on the action of the Logout
                // link/button. This just tells Persona to clean up it's data.
                if (navigator.id) {
                    navigator.id.logout();
                }
            });
        }
        $(logout);
        z.page.on('fragmentloaded', logout);
    })();
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

    var personaInterval;

    function waitForPersona() {
        if (navigator.id) {
            clearInterval(personaInterval);
            setupPersona();
        }
    }

    function setupPersona() {
        var email = '';
        if ($('body').data('user')) {
            email = $('body').data('user').email;
        }
        console.log('detected user ' + email);
        navigator.id.watch({
            loggedInUser: email,
            onlogin: function(assert) {
                gotVerifiedEmail(assert);
            },
            onlogout: function() {
            }
        });
    }

    function initPersona() {
        // Persona may not be completely initialized at page ready.
        // This can cause the .watch function to not be set.
        if (navigator.id) {
            setupPersona();
        } else {
            personaInterval = setTimeout(waitForPersona, 500));
        }
    }

    $(document).ready(initPersona);

});
