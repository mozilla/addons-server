/*
 * WARNING: THIS FILE IS MOST LIKELY OBSOLETE. SEE media/js/devreg/login.js
 */


function browserIDRedirect(to, options) {
    if (!options) options = {};
    return function(data, textStatus, jqXHR) {
        if (to) {
            if(typeof to == "object") {
                to['on'].removeClass('loading-submit').trigger(to['fire']);
            } else {
                window.location = to;
            }
        }
    };
}

function gotVerifiedEmail(assertion, redirectTo, domContext) {
    function displayErrBox(errmsg) {
        $('.loading-submit').removeClass('loading-submit');

        $('section.primary', domContext).eq(0).prepend(
            format('<div class="notification-box error">'
                   + '<ul><h2>{0}</h2></ul></div>', [errmsg]));
    }
    if (assertion) {
        var a = $.ajax({
            url: $('.browserid-login', domContext).attr('data-url'),
            type: 'POST',
            data: {
                'assertion': assertion
            },
            success: browserIDRedirect(redirectTo),
            error: function(jqXHR, textStatus, errorThrown) {
                if (jqXHR.status == 400) {
                    displayErrBox(gettext('Admins and editors must ' +
                                          'provide a password to log in.'));
                } else {
                    var msg = jqXHR.responseText;
                    if (!msg) {
                        msg = gettext("BrowserID login failed. Maybe you don't have an account under that email address?") +
                                      " " + textStatus + " " + errorThrown;
                    }
                    displayErrBox(msg);
                }
            }
        });
        return a;
    } else {
        // user clicked 'cancel', don't do anything
        $('.loading-submit').removeClass('loading-submit');
        return null;
    };
}

function initBrowserID(win, ctx) {
    // Initialize BrowserID login.
    if ($('body').data('pers-handle')) {
        return;
    } else {
        // call DIBS on persona event handling.
        $('body').data('pers-handle', true);
    }
    var toArg = win.location.href.split('?to=')[1],
        to = "/";

    if (toArg) {
        to = decodeURIComponent(toArg);
        // Don't redirect to external sites
        if (to.indexOf("://") > -1) to = "/";
    } else if(win.location.href.indexOf('://') == -1 && win.location.href.indexOf('users/login') == -1) {
        // No 'to' and not a log in page; redirect to the current page
        to = win.location.href;
    }
    $(ctx || win).delegate('.browserid-login', 'click', function(e) {
        var $el = $(this),
            // If there's a data-event on the login button, fire that event
            // instead of redirecting the browser.
            event = $el.attr('data-event'),
            redirectTo = event ? {'fire': event, 'on': $el} : to;

        e.preventDefault();
        $el.addClass('loading-submit');
        $('.primary .notification-box', ctx).remove();
        navigator.id.watch({
            onlogin: function(assertion) {
                gotVerifiedEmail(assertion, redirectTo);
            },
            onlogout: function() {
                // even if no action, this must be included.
            }
        });
    });
}

$(document).ready(function () {initBrowserID(window);});

