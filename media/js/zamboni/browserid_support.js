
function browserIDRedirect(to) {
    return function(data, textStatus, jqXHR) {
        if (to) {
            window.location = to;
        }
    };
}

function gotVerifiedEmail(assertion, redirectTo, domContext) {
    function displayErrBox(errmsg) {

        $('section.primary', domContext).prepend(
            format('<div class="notification-box error">'
                   + '<ul><h2>{0}</h2></ul></div>', [errmsg]));
    }
    if (assertion) {
        var a = $.ajax({
                   url: $('.browserid-login', domContext).attr('data-url'),
                   type: 'POST',
                   data: {
                       'audience': document.location.host,
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
                           displayErrBox(gettext(
                                  "BrowserID login failed. Maybe you don't "
                                + 'have an account under that email address?') +
                                " textStatus: " + textStatus + " errorThrown: " +
                                errorThrown);
                       }
                   }
                   });
        return a;
    } else {
        // user clicked 'cancel', don't do anything
        return null;
    };
}

$(document).ready(function(){
    // Initialize BrowserID login.
    $('.browserid-login').each(function() {
            var to = decodeURIComponent(window.location.href.split('?to=')[1]);
            if (to.indexOf("://") > -1) {
                to = "/";
            };
            $(this).click(
                function (e) {
                    $('.primary .notification-box').remove();
                    navigator.id.getVerifiedEmail(
                        function(assertion) {
                            gotVerifiedEmail(assertion, to);
                });
        });});
});
