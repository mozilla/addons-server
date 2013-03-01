var z = {
    win: $(window),
    doc: $(document),
    body: $(document.body),
    page: $('#page'),
    prefix: (function() {
        var s = window.getComputedStyle(document.body, '');
        return (Array.prototype.slice.call(s).join('').match(/moz|webkit|ms|khtml/)||(s.OLink===''&&['o']))[0];
    })(),
    prefixed: function(property) {
        if (!z.prefix) return property;
        return '-' + z.prefix + '-' + property;
    },
    canInstallApps: !!(navigator.apps || navigator.mozApps),
    state: {mozApps: {}}
};

var data_user = $('body').data('user');
_.extend(z, {
    anonymous: data_user.anonymous,
    pre_auth: data_user.pre_auth
});

$(document).ready(function() {
    // Initialize email links.
    $('span.emaillink').each(function() {
        var $this = $(this);
        $this.find('.i').remove();
        var em = $this.text().split('').reverse().join('');
        $this.prev('a').attr('href', 'mailto:' + em);
    });

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

    z.apps = {};
    if (z.capabilities.webApps) {
        // Get list of installed apps and mark as such.
        r = navigator.mozApps.getInstalled();
        r.onsuccess = function() {
            _.each(r.result, function(val) {
                z.apps[val.manifestURL] = val;
                $(window).trigger('app_install_success',
                                  [val, {'manifest_url': val.manifestURL}, false]);
            });
        };
    }

    // We would use :hover, but we want to hide the menu on fragment load!
    z.body.on('mouseover', '.account-links', function() {
        $('.account-links').addClass('active');
    }).on('mouseout', '.account-links', function() {
        $('.account-links').removeClass('active');
    }).on('click', '.account-links a', function() {
        $('.account-links').removeClass('active');
    }).on('mouseover', '.header-button.submit', function() {
        $('.account-links').removeClass('active');
    });
});


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
