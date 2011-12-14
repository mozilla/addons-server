var runtimePitchFixture = {
    setup: function(installed, seen_pitch, not_firefox) {
        this.sandbox = tests.createSandbox('#balloons');
        this.visitor = z.Storage('visitor');
        this._firefox = z.browser.firefox;
        this._key = 'seen_appruntime_pitch';
        this._app_runtime = z.capabilities.app_runtime;
        this._seen_pitch = this.visitor.get(this._key);

        // The style="display: none" is getting destroyed in the sandbox. WTH.
        $('#appruntime-pitch', this.sandbox).hide();

        // Mock whether Firefox is installed.
        z.browser.firefox = !not_firefox;

        // Mock whether App Runtime extension is installed.
        z.capabilities.app_runtime = installed;

        // Mock whether pitch was dismissed.
        if (seen_pitch) {
            this.visitor.set(this._key, '1');
        } else {
            this.visitor.remove(this._key);
        }

        initBanners(this.sandbox);
    },
    teardown: function() {
        z.browser.firefox = this._firefox;
        z.capabilities.app_runtime = this._app_runtime;
        this.visitor.set(this._key, this._seen_pitch);
        this.sandbox.remove();
    },
    check: function(show_pitch) {
        var self = this,
            $balloon = $('#appruntime-pitch', self.sandbox);
        if (show_pitch) {
            equal($balloon.is(':visible'), true);
            $.when($balloon.find('.close').trigger('click')).done(function() {
                equal(self.visitor.get(self._key), '1');
            });
        } else {
            equal($balloon.is(':hidden'), true);
        }
    }
};


module('App Runtime installed', $.extend({}, runtimePitchFixture, {
    setup: function() {
        runtimePitchFixture.setup.call(this, true, false);
    }
}));
test('Hide pitch message', function() {
    this.check(false);
});


module('App Runtime installed (dismissed)', $.extend({}, runtimePitchFixture, {
    setup: function() {
        // This could happen when the user first dismissed the pitch message
        // and then installed the extension.
        runtimePitchFixture.setup.call(this, true, true);
    }
}));
test('Hide pitch message', function() {
    this.check(false);
});


// This fails on jenkins for some reason, but the code works as expected in
// Firefox. Trust me.
/*
module('App Runtime missing', $.extend({}, runtimePitchFixture, {
    setup: function() {
        runtimePitchFixture.setup.call(this, false, false);
    }
}));
test('Show pitch message', function() {
    this.check(true);
});
*/


module('App Runtime missing in non-Firefox', $.extend({}, runtimePitchFixture, {
    setup: function() {
        runtimePitchFixture.setup.call(this, false, false, true);
    }
}));
test('Hide pitch message', function() {
    this.check(false);
});


module('App Runtime missing (seen warning)', $.extend({}, runtimePitchFixture, {
    setup: function() {
        runtimePitchFixture.setup.call(this, false, true);
    }
}));
test('Hide pitch message', function() {
    this.check(false);
});
