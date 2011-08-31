/* Global initialization script */
var z = {};

function makeRedirectAfterBrowserIDLogin(to) {
    return function(data, textStatus, jqXHR) {
        if (to) {
            window.location = to;
        }
    };
}

function gotVerifiedEmail(assertion, redirectTo, domContext) {
    function displayErrBox(errmsg) {

        $('.primary', domContext).prepend(
            '<div class="notification-box error">'
          + '<ul><h2>' + errmsg + '</h2></ul></div>');
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
                   success: makeRedirectAfterBrowserIDLogin(redirectTo),
                   error: function(jqXHR, textStatus, errorThrown) {
                       displayErrBox(gettext(
                                  'BrowserID login failed. Maybe you don\'t '
                                + 'have an account under that email address?'));}
                   });
        return a;
    } else {
        // user clicked 'cancel', don't do anything
        return null;
    };
}

$(document).ready(function(){

    // Initialize install buttons.
    $('.install').installButton();
    if ($('.backup-button').length) {
        $('.backup-button').showBackupButton();
    }

    // Initialize any tabbed interfaces.  See: tabs.js
    if ($.fn.tabify) {
        $('.tab-wrapper').tabify();
    }

    // Initialize email links
    $('span.emaillink').each(function() {
        $(this).find('.i').remove();
        var em = $(this).text().split('').reverse().join('');
        $(this).prev('a').attr('href', 'mailto:' + em).addClass('email');
    });
    // Initialize BrowserID login.
    $('.browserid-login').each(
        function() {
            var to = decodeURIComponent(window.location.href.split('?to=')[1]);
            $(this).click(
                function (e) {
                    $('.primary .notification-box').remove();
                    navigator.id.getVerifiedEmail(
                        function(assertion) {
                            gotVerifiedEmail(assertion, to);
                });
        });});
    // fake placeholders if we need to.
    if (!('placeholder' in document.createElement('input'))) {
        $('input[placeholder]').placeholder();
    }

    if (z.readonly) {
        $('form[method=post]')
            .before(gettext('This feature is temporarily disabled while we perform website maintenance. Please check back a little later.'))
            .find('input, button, select').attr('disabled', true);
    }
});

z.inlineSVG = (function() {
  var e = document.createElement('div');
  e.innerHTML = '<svg></svg>';
  return !!(window.SVGSVGElement && e.firstChild instanceof window.SVGSVGElement);
})();
if (!z.inlineSVG) {
    $("body").addClass("noInlineSVG");
}
z.cssTransitions = (function() {
    var shim = document.createElement('div');
    shim.innerHTML = '<div style="-webkit-transition:color 1s linear;-moz-transition:color 1s linear;"></div>';
    var test = document.body.style.webkitTransition !== undefined ||
               document.body.style.MozTransition !== undefined;
    return test;
})();
z.hasTruncation = (function() {
    var shim = document.createElement('div');
    shim.innerHTML = '<div style="text-overflow: ellipsis"></div>';
    var s = shim.firstChild.style;
    return 'textOverflow' in s || 'OTextOverflow' in s;
})();

/* prevent-default function wrapper */
function _pd(func) {
    return function(e) {
        e.preventDefault();
        func.apply(this, arguments);
    };
}


/* Fake the placeholder attribute since Firefox 3.6 doesn't support it. */
jQuery.fn.placeholder = function(new_value) {

    if (new_value) {
        this.attr('placeholder', new_value);
    }

    /* Bail early if we have built-in placeholder support. */
    if ('placeholder' in document.createElement('input')) {
        return this;
    }

    if (new_value && this.hasClass('placeholder')) {
        this.val('').blur();
    }

    return this.focus(function() {
        var $this = $(this),
            text = $this.attr('placeholder');

        if ($this.val() == text) {
            $this.val('').removeClass('placeholder');
        }
    }).blur(function() {
        var $this = $(this),
            text = $this.attr('placeholder');

        if ($this.val() == '') {
            $this.val(text).addClass('placeholder');
        }
    }).each(function(){
        /* Remove the placeholder text before submitting the form. */
        var self = $(this);
        self.closest('form').submit(function() {
            if (self.hasClass('placeholder')) {
                self.val('');
            }
        });
    }).blur();
};


jQuery.fn.hasattr = function(name) {
    return this.attr(name) !== undefined;
}


var escape_ = function(s){
    return s.replace('&', '&amp;').replace('>', '&gt;').replace('<', '&lt;')
            .replace("'", '&#39;').replace('"', '&#34;');
};

//TODO(potch): kill underscore dead. until then, fake it on mobile.
if (!('_' in window)) _ = {};
/* is ``key`` in obj? */
_.haskey = function(obj, key) {
    return typeof obj[key] !== "undefined";
};


/* Detect browser, version, and OS. */
$.extend(z, BrowserUtils());
$(document.body).addClass(z.platform).toggleClass('badbrowser', z.badBrowser);


/* Details for the current application. */
z.app = document.body.getAttribute('data-app');
z.appName = document.body.getAttribute('data-appname');
z.appMatchesUserAgent = z.browser[z.app];

z.anonymous = JSON.parse(document.body.getAttribute('data-anonymous'))

z.media_url = document.body.getAttribute('data-media-url');

z.readonly = JSON.parse(document.body.getAttribute('data-readonly'));

if (z.browser.firefox) {
    var nightlyVer = document.body.getAttribute('data-nightly-version');
    if (nightlyVer) {
        z.hasNightly = (VersionCompare.compareVersions(z.browserVersion, nightlyVer) > -1);
    } else {
        z.hasNightly = false;
    }
    var betaVer = document.body.getAttribute('data-min-beta-version');
    z.fxBeta = (VersionCompare.compareVersions(z.browserVersion, betaVer) > -1);
    if (z.fxBeta) {
        $(document.body).addClass('fxbeta');
    }
} else {
    z.fxBeta = false;
}

if (z.badBrowser) {
    $(".get-fx-message").show();
}