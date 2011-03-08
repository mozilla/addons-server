$(document).ready(function(){

var editorFixtures = {
    setup: function() {
        this.sandbox = tests.createSandbox('#editors-search-form');
        initQueueSearch(this.sandbox);
    },
    teardown: function() {
        this.sandbox.remove();
    },
    selectOpt: function(index) {
        var doc = this.sandbox;
        $('#id_application_id option', doc).eq(index).attr('selected', 'selected');
        $('#id_application_id', doc).trigger('change');
    }
};

module('editors search form 1', editorFixtures);

asyncTest('select application', function() {
    var doc = this.sandbox;
    $.mockjax({
        url: '/application_versions.json',
        status: 200,
        response: function(settings) {
            equals(settings.data.application_id, '1');
            this.responseText = {
                choices: [['', ''],
                          ['4.0b2pre', '4.0b2pre'],
                          ['2.0a1pre', '2.0a1pre'],
                          ['1.0', '1.0']]
            };
        }
    });
    this.selectOpt(1);
    tests.waitFor(function() {
        return ($('#id_max_version option', doc).length > 1);
    }).thenDo(function() {
        var values = [];
        $.each($('#id_max_version option', doc), function(i, e) {
            values.push($(e).val());
        });
        same(values, ["", "4.0b2pre", "2.0a1pre", "1.0"]);
        start();
    });
});

module('editors search form 2', editorFixtures);

asyncTest('de-select application', function() {
    var suite = this,
        doc = this.sandbox;
    $.mockjax({
        url: '/application_versions.json',
        status: 200,
        responseText: {choices: [['', ''], ['4.0b2pre', '4.0b2pre']]}
    });
    suite.selectOpt(1);
    tests.waitFor(function() {
        return ($('#id_max_version option', doc).length > 1);
    }).thenDo(function() {
        suite.selectOpt(0);
        tests.waitFor(function() {
            return ($('#id_max_version option', doc).length == 1);
        }).thenDo(function() {
            equals($('#id_max_version option', doc).text(),
                   'Select an application first');
            start();
        });
    });
});

module('editors MOTD', {
    setup: function() {
        Storage.remove('motd_closed');
        this.sandbox = tests.createSandbox('#editors-motd-template');
        $('.daily-message .close', this.sandbox).hide();
        initDailyMessage(this.sandbox);
    },
    teardown: function() {
        this.sandbox.remove();
    }
});

test('is closable', function() {
    var doc = this.sandbox;
    equals($('.daily-message .close:visible', doc).length, 1);
});

asyncTest('click to close', function() {
    var doc = this.sandbox;
    $('.daily-message .close', doc).trigger('click');
    tests.waitFor(function() {
        return $('.daily-message .close:visible', doc).length == 0;
    }).thenDo(function() {
        ok(true, 'message was closed');
        start();
    });
});

module('editors MOTD page', {
    setup: function() {
        this.sandbox = tests.createSandbox('#editors-motd-for-edit-template');
        $('.daily-message .close', this.sandbox).hide();
        initDailyMessage(this.sandbox);
    },
    teardown: function() {
        this.sandbox.remove();
    }
});

test('not closable', function() {
    var doc = this.sandbox;
    equals($('.daily-message .close:visible', doc).length, 0);
});

module('editors MOTD after clicking', {
    setup: function() {
        Storage.set('motd_closed', 'This is an announcement');
        this.sandbox = tests.createSandbox('#editors-motd-template');
        initDailyMessage(this.sandbox);
    },
    teardown: function() {
        this.sandbox.remove();
    }
});

test('message hidden', function() {
    var doc = this.sandbox;
    equals($('.daily-message .close:visible', doc).length, 0);
});



});
