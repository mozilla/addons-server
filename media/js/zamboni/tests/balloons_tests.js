$(document).ready(function() {
    var openWebAppsFixture = {
        setup: function(hasAppsSupport, hasSeenAppsSupportWarning) {
            this.sandbox = tests.createSandbox('#balloons');
            this.visitor = z.Storage('visitor');
            this._seen_noinstall_apps_warning = this.visitor.get('seen_noinstall_apps_warning');
            this.visitor.remove('seen_noinstall_apps_warning');

            var $balloon = $('#site-noinstall-apps', this.sandbox);
            // this is normally ensured via CSS
            $balloon.hide();

            // this is the logic being mocked from global.js
            if (!hasAppsSupport && !hasSeenAppsSupportWarning) {
                $balloon.show();
            }
        },
        teardown: function() {
            this.visitor.set('seen_noinstall_apps_warning', this._seen_noinstall_apps_warning);
            this.sandbox.remove();
        },
        check: function(showWarning) {
            var self = this;
            if (showWarning) {
                equal($('#site-noinstall-apps:visible', this.sandbox).length, 1);
                $.when($('#site-noinstall-apps .close', this.sandbox).click()).done(function() {
                    equal(self.visitor.get('seen_noinstall_apps_warning'), '1');
                });
            } else {
                equal(this.visitor.get('seen_noinstall_apps_warning'), undefined);
                equal($('#site-noinstall-apps:hidden', this.sandbox).length, 1);
            }
        }
    };

    module('Browser has Open Web Apps Support', $.extend({}, openWebAppsFixture, {
        setup: function() {
            // Browser has Open Web Apps support (.mozApps) and user hasn't seen the warning
            openWebAppsFixture.setup.call(this, true, false);
        }
    }));
    test('No warning balloon', function() {
        this.check(false);
    });

    module('Browser has Open Web Apps Support (seen warning)', $.extend({}, openWebAppsFixture, {
        setup: function() {
            // Browser has OWA support (.mozApps) and user has seen the warning
            openWebAppsFixture.setup.call(this, true, true);
        }
    }));
    test('No warning balloon', function() {
        this.check(false);
    });

    module('Browser has no Open Web Apps Support', $.extend({}, openWebAppsFixture, {
        setup: function() {
            // Browser has no OWA support and user hasn't seen the warning
            openWebAppsFixture.setup.call(this, false, false);
        }
    }));
    test('Show warning balloon', function() {
        this.check(true);
    });

    module('Browser has no Open Web Apps Support (seen warning)', $.extend({}, openWebAppsFixture, {
        setup: function() {
            // Browser has no OWA support and user has seen the warning
            openWebAppsFixture.setup.call(this, false, true);
        }
    }));
    test('No warning balloon', function() {
        this.check(false);
    });

});
