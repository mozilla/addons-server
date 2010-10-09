/* Global initialization script */
z = {};

$(".js-hidden").hide();

$(document).ready(function(){

    // Initialize install buttons.
    $('.install').installButton();

    // Initialize any translation boxes. See: translations/trans.js
    if ($.fn.transbox) {
        $('.trans').transbox();
    }

    // Initialize any tabbed interfaces.  See: tabs.js
    if ($.fn.tabify) {
        $('.tab-wrapper').tabify();
    }

    // Initialize email links
    $('span.emaillink').each(function() {
        $(this).find('.i').remove();
        em = $(this).text().split('').reverse().join('');
        a = $('<a>').attr('href', 'mailto:' + em)
            .text(em);
        $(this).replaceWith(a);
    });

    // Set up input placeholders.
    $('input[placeholder]').placeholder();

    // Set up advanced search box.
    z.searchBox();

    if (z.readonly) {
        $('form[method=post]')
            .before(gettext('This feature is temporarily disabled while we perform website maintenance. Please check back a little later.'))
            .find('input, button, select').attr('disabled', true);
    }
});


/* Python(ish) string formatting:
 * >>> format('{0}', ['zzz'])
 * "zzz"
 * >>> format('{x}', {x: 1})
 * "1"
 */
function format(s, args) {
    var re = /\{([^}]+)\}/g;
    return s.replace(re, function(_, match){ return args[match]; });
}
function template(s) {
    return function(args) { return format(s, args); };
}

/* Fake the placeholder attribute since Firefox doesn't support it. */
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


jQuery.fn.safeText = function() {
    return escape_(this.text());
};


/* is ``key`` in obj? */
_.haskey = function(obj, key) {
    return typeof obj[key] !== "undefined";
};


/* Turn a list of (key, value) pairs into an object. */
_.dict = function(arr) {
    var rv = {};
    for (k in arr) {
        var pair = arr[k];
        rv[pair[0]] = pair[1];
    }
    return rv;
};

_.items = function(o) {
    return _.zip(_.keys(o), _.values(o));

};


/* Detect browser, version, and OS. */
z.browser = {firefox: false, seamonkey: false, mobile: false,
             thunderbird: false};
z.browserVersion = 0;
z.os = {windows: false, mac: false, linux: false, other: false};

(function(){
    // Globals are coming from amo2009/addons.js.
    var ua = function(browser, pattern) {
        match = pattern.exec(navigator.userAgent);
        if (match && match.length == 3) {
            z.browser[browser] = true;
            z.browserVersion = escape_(match[2]);
        }
    }
    // Mobile comes after Firefox to overwrite the browser version.
    ua('firefox', UA_PATTERN_FIREFOX);
    ua('mobile', UA_PATTERN_MOBILE);
    ua('seamonkey', UA_PATTERN_SEAMONKEY);
    ua('thunderbird', UA_PATTERN_THUNDERBIRD);

    var platform = function(os, needle) {
        if (navigator.platform.indexOf(needle) != -1) {
            $(document.body).addClass(os);
            z.os[os] = true;
            z.platform = os;
        }
    }
    platform('windows', 'Win32');
    platform('mac', 'Mac');
    platform('linux', 'Linux');

    if (!_.any(_.values(z.os))) {
        platform('other', '');
    }
})();

/* Details for the current application. */
z.app = document.body.getAttribute('data-app');
z.appName = document.body.getAttribute('data-appname');
z.appMatchesUserAgent = z.browser[z.app];

z.anonymous = JSON.parse(document.body.getAttribute('data-anonymous'))

z.media_url = document.body.getAttribute('data-media-url');

z.readonly = JSON.parse(document.body.getAttribute('data-readonly'));
