
function browserIDRedirect(to) {
    return function(data, textStatus, jqXHR) {
        if (to) {
            window.location = to;
        }
    };
}

function gotVerifiedEmail(assertion, redirectTo, domContext) {
    function displayErrBox(errmsg) {
        $('.loading-submit').removeClass('loading-submit');

        $('section.primary', domContext).prepend(
            format('<div class="notification-box error">'
                   + '<ul><h2>{0}</h2></ul></div>', [errmsg]));
    }
    if (assertion) {
        var a = $.ajax({
                   url: $('.browserid-login', domContext).attr('data-url'),
                   type: 'POST',
                   data: {
                       'assertion': assertion,
                       'csrfmiddlewaretoken':
                       $('input[name=csrfmiddlewaretoken]').val()
                   },
                   success: browserIDRedirect(redirectTo),
                   error: function(jqXHR, textStatus, errorThrown) {
                       if (jqXHR.status == 400) {
                           displayErrBox(gettext(
                                  'Admins and editors must provide'
                                + ' a password to log in.'));
                       } else {
                         var msg = jqXHR.responseText;
                         if (!msg) {
                           msg = gettext(
                             "BrowserID login failed. Maybe you don't" +
                               " have an account under that email address?") +
                             " textStatus: " + textStatus + " errorThrown: " +
                             errorThrown;
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
    $('.browserid-login', ctx).each(function() {
            var toArg = win.location.href.split('?to=')[1];
            var to = "/";
            if (toArg) {
              to = decodeURIComponent(toArg);
            }
            if (to.indexOf("://") > -1) {
                to = "/";
            };
            $(this).click(
                function (e) {
                    $(this).addClass('loading-submit');
                    $('.primary .notification-box', ctx).remove();
                    navigator.id.getVerifiedEmail(
                        function(assertion) {
                            gotVerifiedEmail(assertion, to);
                });
        });});
}
$(document).ready(function () {initBrowserID(window);});

