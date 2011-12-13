function browserIDRedirect(to, options) {
    if (!options) options = {};
    return function(data, textStatus, jqXHR) {
        if (data.profile_needs_completion) {
            // Ask registrant to complete her profile before redirecting.
            var def = completeUserProfile($.extend({}, options, {to: to}))
                        .done(function() {
                            $('.loading-submit').removeClass('loading-submit');
                            if(typeof to == "object") {
                                to['on'].removeClass('loading-submit');
                            }
                        });
            return def;
        }
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
                                      " textStatus: " + textStatus + " errorThrown: " + errorThrown;
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
        navigator.id.getVerifiedEmail(function(assertion) {
            gotVerifiedEmail(assertion, redirectTo);
        });
    });
}

function completeUserProfile(options) {
    if (!options) options = {};
    var $doc = options.doc || $(document),
        $root = $('#login-complete-profile', $doc),
        profileFormUrl = $('.browserid-login', $doc).attr('data-profile-form-url');
    if (!profileFormUrl) {
        throw new Error('misconfiguration: could not find data-profile-form-url');
    }
    if (!$root.length) {
        // Complete profile via modal since we are probably not on the login page.
        var def = $.Deferred();
        modalFromURL(profileFormUrl, {callback: function() {
            def.resolve();
            var $box = $(this);
            $box.attr('id', 'login-complete-profile');  // for styles
            loadProfileCompletionForm($box, options);
        }, 'deleteme': false, 'close': false, 'hideme': false});
        return def;
    }
    $root.empty();
    // Load form HTML via Ajax to get a unique CSRF token.
    return $.ajax({url: profileFormUrl, type: 'GET', dataType: 'html'})
                  .done(function(html) {
                       $root.html(html);
                       loadProfileCompletionForm($root, options);
                  })
                  .fail(function(xhr, textStatus, errorThrown) {
                       if (typeof console !== 'undefined') {
                           console.log('error:', xhr);
                       }
                  });
}

function loadProfileCompletionForm($root, options) {
    if (!options) options = {};
    var $error = $('.notification-box.error', $root),
        win = options.window || window;

    $('#browserid-login').hide(); // Don't let people log in twice; will cause error
    $(window).trigger('resize'); // I hate this so much. I vow to someday fix this properly.

    $('input[type="text"]', $root).eq(0).focus();
    $('form', $root).submit(function(evt) {
        var $form = $(this);
        evt.preventDefault();
        $error.hide();
        $('button[type="submit"]', $form).addClass('loading-submit');
        $.ajax({url: $form.attr('action'),
                type: 'POST',
                data: $form.serialize(),
                dataType: 'json'})
               .always(function() {
                   $('button[type="submit"]', $form).removeClass('loading-submit');
               })
               .done(function(data) {
                   if (options.to) {
                       if (typeof options.to === 'object') {
                           options.to['on'].trigger(options.to['fire']);
                       } else {
                           win.location = options.to;
                       }
                   } else {
                       win.location = $form.attr('data-post-login-url');
                   }
                   $form.trigger('success.profile_completion');
               })
               .fail(function(xhr, textStatus, errorThrown) {
                   var msg = [], data, ul = $('<ul></ul>');
                   try {
                       data = $.parseJSON(xhr.responseText);
                   } catch (err) {}
                   if (data) {
                       // {username: ['already exists']...}
                       $.each(data, function(field, errors) {
                           $.each(errors, function(i, m) {
                               msg.push($form.find('label[for="id_' + field + '"]').text() + ': ' + m);
                           });
                       });
                   } else {
                       msg = [gettext('Internal server error')];
                   }
                   $.each(msg, function(i, m) {
                       ul.append('<li>' + m + '</li>');
                   });
                   $error.html(ul).show();
                   $form.trigger('badresponse.profile_completion');
               });
    });
}

$(document).ready(function () {initBrowserID(window);});

