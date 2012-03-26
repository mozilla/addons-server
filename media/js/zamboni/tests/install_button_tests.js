$(document).ready(function() {
    var installButtonFixture = {
        setup: function(sandboxId) {
            this.sandbox = tests.createSandbox(sandboxId);
            this.button = $('.button', this.sandbox);
            this.expected = {};
        },
        teardown: function() {
            this.sandbox.remove();
        },
        check: function(expected) {
            for (var prop in expected) {
                if (expected.hasOwnProperty(prop)) {
                    equal(this.button.attr(prop), expected[prop]);
                }
            }
        }
    };

    module('Install Button', $.extend({}, installButtonFixture, {
        setup: function() {
            installButtonFixture.setup.call(this, '#install-button-warning');
        }
    }));
    test('app, warning, mobile', function() {
        this.expected['data-hash'] = undefined;
        this.expected['href'] = '#';
        this.expected['data-realurl'] = undefined;

        this.check(this.expected);
    });

    module('Install Button', $.extend({}, installButtonFixture, {
        setup: function() {
            installButtonFixture.setup.call(this, '#install-button-eula');
        }
    }));
    test('app, eula, mobile', function() {
        this.expected['data-hash'] = undefined;
        this.expected['href'] = '#';
        this.expected['data-realurl'] = undefined;

        this.check(this.expected);
    });

    module('Install Button', $.extend({}, installButtonFixture, {
        setup: function() {
            installButtonFixture.setup.call(this, '#install-button-premium');
        }
    }));
    test('premium, mobile', function() {
        this.expected['data-hash'] = undefined;
        this.expected['href'] = 'http://testurl.com';
        this.expected['data-realurl'] = undefined;

        this.check(this.expected);
    });

    module('Install Button', $.extend({}, installButtonFixture, {
        setup: function() {
            installButtonFixture.setup.call(this, '#install-button-contrib');
        }
    }));
    test('contrib, mobile', function() {
        this.expected['data-hash'] = '1337';
        this.expected['href'] = 'http://testurl.com';
        this.expected['data-realurl'] = undefined;

        this.check(this.expected);
    });

    module('Install Button', $.extend({}, installButtonFixture, {
        setup: function() {
            installButtonFixture.setup.call(this, '#install-button-purchasable');
        }
    }));
    test('can be purchased, mobile', function() {
        this.expected['data-hash'] = '1337';
        this.expected['href'] = 'http://testurl.com';
        this.expected['data-realurl'] = undefined;

        this.check(this.expected);
    });

    module('Install Button', $.extend({}, installButtonFixture, {
        setup: function() {
            installButtonFixture.setup.call(this, '#install-button-app-premium');
        }
    }));
    test('app, premium, mobile', function() {
        this.expected['data-hash'] = undefined;
        this.expected['href'] = '#';
        this.expected['data-realurl'] = undefined;

        this.check(this.expected);
    });

    module('Install Button', $.extend({}, installButtonFixture, {
        setup: function() {
            installButtonFixture.setup.call(this, '#install-button-app-contrib');
        }
    }));
    test('app, contrib, mobile', function() {
        this.expected['data-hash'] = undefined;
        this.expected['href'] = '#';
        this.expected['data-realurl'] = undefined;

        this.check(this.expected);
    });

    module('Install Button', $.extend({}, installButtonFixture, {
        setup: function() {
            installButtonFixture.setup.call(this, '#install-button-app-purchasable');
        }
    }));
    test('app, can be purchased, mobile', function() {
        this.expected['data-hash'] = undefined;
        this.expected['href'] = '#';
        this.expected['data-realurl'] = undefined;

        this.check(this.expected);
    });

    module('Install Button', $.extend({}, installButtonFixture, {
        setup: function() {
            installButtonFixture.setup.call(this, '#install-button-mp-warning');
        }
    }));
    test('marketplace, app, warning, mobile', function() {
        this.expected['data-hash'] = undefined;
        this.expected['href'] = '#';
        this.expected['data-realurl'] = undefined;

        this.check(this.expected);
    });

    module('Install Button', $.extend({}, installButtonFixture, {
        setup: function() {
            installButtonFixture.setup.call(this, '#install-button-mp-eula');
        }
    }));
    test('marketplace, app, eula, mobile', function() {
        this.expected['data-hash'] = undefined;
        this.expected['href'] = '#';
        this.expected['data-realurl'] = undefined;

        this.check(this.expected);
    });

    module('Install Button', $.extend({}, installButtonFixture, {
        setup: function() {
            installButtonFixture.setup.call(this, '#install-button-mp-premium');
        }
    }));
    test('marketplace, premium, mobile', function() {
        this.expected['data-hash'] = undefined;
        this.expected['href'] = 'http://testurl.com';
        this.expected['data-realurl'] = undefined;

        this.check(this.expected);
    });

    module('Install Button', $.extend({}, installButtonFixture, {
        setup: function() {
            installButtonFixture.setup.call(this, '#install-button-mp-contrib');
        }
    }));
    test('marketplace, contrib, mobile', function() {
        this.expected['data-hash'] = '1337';
        this.expected['href'] = 'http://testurl.com';
        this.expected['data-realurl'] = undefined;

        this.check(this.expected);
    });

    // All compatible.
    module('D2C Install Button', $.extend({}, installButtonFixture, {
        setup: function() {
            installButtonFixture.setup.call(this, '#button-d2c-compatible');
        }
    }));
    test('d2c, is_compatible', function() {
        this.expected['class'] = 'button add installer';
        this.check(this.expected);
        equal($('.extra', this.sandbox).length, 0);

    });

    // Compatible, but with an override.
    module('D2C Install Button', $.extend({}, installButtonFixture, {
        setup: function() {
            installButtonFixture.setup.call(this, '#button-d2c-compatible-override');
        }
    }));
    test('d2c, is_compatible, override', function() {
        this.expected['class'] = 'button add concealed';
        this.check(this.expected);
        equal($('.extra', this.sandbox).length, 1);
        equal($('.notavail', this.sandbox).text().substr(0, 13), 'Not available');
    });

    // Server side checks are incompatible.
    module('D2C Install Button', $.extend({}, installButtonFixture, {
        setup: function() {
            installButtonFixture.setup.call(this, '#button-d2c-not-compatible');
        }
    }));
    test('d2c, not is_compatible', function() {
        this.expected['class'] = 'button add concealed';
        this.check(this.expected);
        equal($('.extra', this.sandbox).length, 1);
        equal($('.notavail', this.sandbox).text().substr(0, 13), 'Not available');
    });

});
