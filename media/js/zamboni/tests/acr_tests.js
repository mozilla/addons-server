$(document).ready(function() {

    var acrFixture = {
        setup: function(browserVersion, hasNightly, maxVer) {
            this.sandbox = tests.createSandbox('#acr');
            this._browser = z.browserVersion;
            this._hasNightly = z.hasNightly;
            this._hasACR = z.hasACR;
            z.browserVersion = browserVersion;
            z.hasNightly = hasNightly;
            z.hasACR = false;
            $(document.body).removeClass('acr-pitch');
            if (maxVer) {
                $('.install', this.sandbox).attr('data-max', maxVer);
            }
            $('.install', this.sandbox).installButton();
            initBanners(this.sandbox);
        },
        teardown: function() {
            z.browserVersion = this._browser;
            z.hasNightly = this._hasNightly;
            z.hasACR = this._hasACR;
            $(document.body).removeClass('acr-pitch');
            this.sandbox.remove();
        },
        check: function(showPitch) {
            var $body = $(document.body);
            if ($body.hasClass('badbrowser')) {
                return;
            }
            var max = $('.install', this.sandbox).attr('data-max'),
                newerBrowser = VersionCompare.compareVersions(z.browserVersion, max) > 0;
            if (showPitch) {
                equals(newerBrowser, true);
                tests.hasClass($body, 'acr-pitch');
                equals($('#acr-pitch:visible', this.sandbox).length, 1);
            } else {
                equals(newerBrowser, false);
                tests.lacksClass($body, 'acr-pitch');
                equals($('#acr-pitch:hidden', this.sandbox).length, 1);
            }
        }
    };

    module('ACR nightly incompatible', $.extend({}, acrFixture, {
        setup: function() {
            // 3.0 is older than Nightly (which we're pretending is 8.0), so
            // this is certainly incompatible.
            acrFixture.setup.call(this,
                $(document.body).attr('data-nightly-version'), true, '3.0');
        }
    }));
    test('Show pitch', function() {
        this.check(true);
    });

    module('ACR nightly compatible', $.extend({}, acrFixture, {
        setup: function() {
            var nightlyVer = $(document.body).attr('data-nightly-version');
            // We're running Nightly, and we're going to pretend all the
            // add-ons are compatible with 8.0.
            acrFixture.setup.call(this, nightlyVer, true, nightlyVer);
        }
    }));
    test('No pitch', function() {
        this.check(false);
    });

    module('ACR non-nightly compatible', $.extend({}, acrFixture, {
        setup: function() {
            acrFixture.setup.call(this, '4.0', false);
        }
    }));
    test('No pitch', function() {
        this.check(false);
    });


    var acrOverrideFixture = {
        setup: function(browserVersion, hasACR, maxVer) {
            this.sandbox = tests.createSandbox('#acr-override');
            this._browser = z.browserVersion;
            this._hasACR = z.hasACR;
            z.browserVersion = browserVersion;
            z.hasACR = hasACR != null ? hasACR : false;
            $(document.body).removeClass('acr-pitch');
            if (maxVer) {
                $('.install-shell > div', this.sandbox).attr('data-max', maxVer);
            }
            $('.install-shell > div', this.sandbox).installButton();
            this.buttons = $('.install-shell', this.sandbox);
            this.override_msg = 'May be incompatible with Firefox ' + z.browserVersion;
            this.notavail_msg = 'Not available for Firefox ' + z.browserVersion;
        },
        teardown: function() {
            z.browserVersion = this._browser;
            z.hasACR = this._hasACR;
            $(document.body).removeClass('acr-pitch');
            this.sandbox.remove();
        },
        isCompat: function(el) {
            equals(el.find('.extra').length, 0);
            equals(el.find('.add').text(), 'Add to Firefox');
        },
        notAvail: function(el) {
            tests.lacksClass(el.find('.notavail'), 'acr-incompat');
            equals(el.find('.notavail').text(), this.notavail_msg);
            equals(el.find('.concealed').text(), 'Add to Firefox');
        },
        mayCompat: function(el) {
            equals(el.find('.notavail.acr-incompat').text(), this.override_msg);
            equals(el.find('.add.acr-override').text(), 'Add to Firefox');
        }
    };


    module('ACR installed: override for incompatible maxVer', $.extend({}, acrOverrideFixture, {
        setup: function() {
            // We're running 9.0.
            acrOverrideFixture.setup.call(this, '9.0', true);
        }
    }));
    test('Firefox: Pre-Release Version', function() {
        equals(this.buttons.find('div[data-version-supported=true]').length, 1);
        // This one should always be compatible (maxVer is 99.9).
        this.isCompat(this.buttons.eq(0));
        // 9.0 "may be incompatible" (maxVer is 7.*).
        this.mayCompat(this.buttons.eq(1));
    });

    module('ACR installed: override for incompatible minVer', $.extend({}, acrOverrideFixture, {
        setup: function() {
            acrOverrideFixture.setup.call(this, '2.0', true);
        }
    }));
    test('Firefox: Old Version', function() {
        equals(this.buttons.find('div[data-version-supported=true]').length, 1);
        this.isCompat(this.buttons.eq(0));
        // 2.0 "may be incompatible" (minVer is 3.6).
        this.mayCompat(this.buttons.eq(1));
    });

    module('ACR installed: override for compatible', $.extend({}, acrOverrideFixture, {
        setup: function() {
            acrOverrideFixture.setup.call(this, '6.0', true);
        }
    }));
    test('Firefox: Current Version', function() {
        equals(this.buttons.find('div[data-version-supported=true]').length, 2);
        this.isCompat(this.buttons.eq(0));
        // 6.0 should certainly be compatible (2.0 - 7.*).
        this.isCompat(this.buttons.eq(1));
    });

    module('no ACR: incompatible maxVer', $.extend({}, acrOverrideFixture, {
        setup: function() {
            acrOverrideFixture.setup.call(this, '8.0', false);
        }
    }));
    test('Firefox: Pre-Release Version', function() {
        equals(this.buttons.find('div[data-version-supported=true][data-addon=1865]').length, 1);
        this.isCompat(this.buttons.eq(0));  // maxVer is 99.9
        this.notAvail(this.buttons.eq(1));  // maxVer is 7.*
    });

    module('no ACR: incompatible minVer', $.extend({}, acrOverrideFixture, {
        setup: function() {
            acrOverrideFixture.setup.call(this, '2.0', false);
        }
    }));
    test('Firefox: Old Version', function() {
        equals(this.buttons.find('div[data-version-supported=true][data-addon=1865]').length, 1);
        this.isCompat(this.buttons.eq(0));
        this.notAvail(this.buttons.eq(1));  // minVer is 3.6
    });

    module('no ACR: override for compatible', $.extend({}, acrOverrideFixture, {
        setup: function() {
            acrOverrideFixture.setup.call(this, '5.0', false);
        }
    }));
    test('Firefox: Current Version', function() {
        equals(this.buttons.find('div[data-version-supported=true]').length, 2);
        this.isCompat(this.buttons.eq(0));
        this.isCompat(this.buttons.eq(1));  // 2.0 - 7.*
    });

});
