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
            if (maxVer) {
                $('.install', this.sandbox).attr('data-max', maxVer);
            }
            $('.install', this.sandbox).installButton();
            initBanners();
        },
        teardown: function() {
            $(document.body).removeClass('acr-pitch');
            z.browserVersion = this._browser;
            z.hasNightly = this._hasNightly;
            z.hasACR = this._hasACR;
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

});
