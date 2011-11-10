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
            installButtonFixture.setup.call(this, '#install-button-marketplace');
        }
    }));
    test('marketplace, mobile, can be purchased', function() {
        this.expected['data-hash'] = '1337';
        this.expected['href'] = 'http://sharedurl.com';
        this.expected['data-realurl'] = 'http://testurl.com';

        this.check(this.expected);
    });

    module('Install Button', $.extend({}, installButtonFixture, {
        setup: function() {
            installButtonFixture.setup.call(this, '#install-button-app-marketplace');
        }
    }));
    test('app, marketplace, mobile, can be purchased', function() {
        this.expected['data-hash'] = undefined;
        this.expected['href'] = 'http://sharedurl.com';
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
});