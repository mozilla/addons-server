var z = {
    page: $('#page'),
    canInstallApps: true
};

(function() {
    _.extend(z, {'nav': BrowserUtils()});
    if (!z.nav.browser.firefox || z.nav.browser.mobile ||
        VersionCompare.compareVersions(z.nav.browserVersion, '15.0a1') < 0) {
        z.canInstallApps = false;
    }
})();

$(document).ready(function() {
    // Initialize email links.
    $('span.emaillink').each(function() {
        var $this = $(this);
        $this.find('.i').remove();
        var em = $this.text().split('').reverse().join('');
        $this.prev('a').attr('href', 'mailto:' + em);
    });

    // Initialize webtrends tracking.
    webtrendsAsyncInit();

    // Fake placeholders if we need to.
    $('input[placeholder]').placeholder();
    if (z.readonly) {
        $('form[method=post]')
            .before(gettext('This feature is temporarily disabled while we ' +
                            'perform website maintenance. Please check back ' +
                            'a little later.'))
            .find('button, input, select, textarea').attr('disabled', true).addClass('disabled');
    }
    var data_user = $('body').data('user');
    _.extend(z, {
        anonymous: data_user.anonymous,
        pre_auth: data_user.pre_auth
    });

    if (!z.canInstallApps) {
        $(window).trigger('app_install_disabled');
    }
});


/* Fake the placeholder attribute since Firefox 3.6 doesn't support it. */
jQuery.fn.placeholder = function(new_value) {
    /* Bail early if we have built-in placeholder support. */
    if ('placeholder' in document.createElement('input')) {
        return this;
    }

    if (new_value) {
        this.attr('placeholder', new_value);
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


function _pd(func) {
    // Prevent-default function wrapper.
    return function(e) {
        e.preventDefault();
        func.apply(this, arguments);
    };
}


function escape_(s) {
    if (typeof s === 'undefined') {
        return;
    }
    return s.replace(/&/g, '&amp;').replace(/>/g, '&gt;').replace(/</g, '&lt;')
            .replace(/'/g, '&#39;').replace(/"/g, '&#34;');
}


z.receiveMessage = function(cb) {
    // Because jQuery chokes, do cross-browser receiving for `postMessage`.
    if (window.addEventListener) {
        window.addEventListener('message', cb, false);
    } else {
        window.attachEvent('onmessage', cb);
    }
};
z.anonymous = JSON.parse(document.body.getAttribute('data-anonymous'));
z.media_url = document.body.getAttribute('data-media-url');
z.readonly = JSON.parse(document.body.getAttribute('data-readonly'));
z.apps = true;
