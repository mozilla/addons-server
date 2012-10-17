$(window).bind('login', function() {
    $('#login').addClass('show');
}).on('click', '.browserid', function(e) {
    $(this).addClass('loading-submit');
    navigator.id.request({termsOfService: '/tos.html',
                          privacyPolicy: '/privacy.html'});
    e.preventDefault();

});
// Hijack the login form to send us to the right place
$("#login form").submit(function(e) {
    e.stopPropagation();
    var $this = $(this),
        action = $this.attr('action') + format("?to={0}", window.location.pathname);
    $this.attr('action', action);
});
$(".logout").bind('click', function(e) {
    // NOTE: Real logout operations happen on the action of the Logout
    // link/button. This just tells Persona to clean up it's data.
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
                    alert(err.msg);
                }
                $.Deferred().reject(err);
            }
        })
    } else {
        $('.loading-submit').removeClass('loading-submit');
    }
}

function finishLogin() {
    var to = z.getVars(window.location.search).to;
    $.Deferred().resolve();
    if (to && to[0] == '/') {
        window.location = to;
    } else {
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
            clearTimeout($('body').data('pers-timeout'));
        }
        $('.browserid').css('cursor', 'pointer');
        var email = '';
        if ($('body').data('user')) {
            email = $('body').data('user').email;
        }
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
