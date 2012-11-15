$(window).bind('login', function() {
    $('#login').addClass('show');
}).on('click', '.browserid', function(e) {
    $(this).addClass('loading-submit');
    navigator.id.request({termsOfService: '/terms-of-use',
                          privacyPolicy: '/privacy-policy'});
    e.preventDefault();

});
// Hijack the login form to send us to the right place
$("#login form").submit(function(e) {
    e.stopPropagation();
    var $this = $(this),
        action = $this.attr('action') + format("?to={0}", window.location.pathname);
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
                var err = {};
                if (jqXHR.status == 400) {
                    $.post('/csrf', function(r) {
                        $('#login form').append($('<input>',
                                        {type:'hidden', value:r.csrf,
                                         name:'csrfmiddlewaretoken'}));
                     });
                     $('#login').addClass('show old');
                } else {
                    err.msg = jqXHR.responseText;
                    if(!err.msg) {
                        err.msg = gettext("BrowserID login failed. Maybe you don't have an account under that email address?") + " " + textStatus + " " + error;
                    }
                    var el = $(err.msg);
                    z.page.trigger('notify', {msg: el.text()});
                }
                $.Deferred().reject(err);
            }
        })
    } else {
        $('.loading-submit').removeClass('loading-submit');
    }
}

function finishLogin() {
    var to = z.getVars().to;
    $.Deferred().resolve();
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
        window.location.reload();
    }
}

function init_persona() {
    // Persona may not be completely initialized at page ready.
    // This can cause the .watch function to not be set.
    // If the attribute isn't present, indicate to the user that things aren't
    // quite ready.
    if(navigator.id) {
        if ($('body').data('pers-timeout')) {
            clearInterval($('body').data('pers-timeout'));
        }
        if ($('body').data('pers-handle')) {
            /// there is another handler already installed.
            return;
        } else {
            // call DIBS on persona event handling
            $('body').data('pers-handle', true);
        }
        $('.browserid').css('cursor', 'pointer');
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
        })
    } else {
        $('.browserid').css('cursor', 'wait');
        if (!$('body').data('pers-timeout')) {
            $('body').data('pers-timeout', setInterval(init_persona, 500));
        }
    }
}

$(document).ready(init_persona);
