$(document).ready(function(){

function pushTiersAndResults(tiers, results) {
    var $suite = $('#addon-validator-suite-test');
    $.each(['1','2','3','4'], function(i, val) {
        tiers.push($('[class~="test-tier"][data-tier="' + val + '"]',
                                                                $suite));
        results.push($('[class~="tier-results"][data-tier="' + val + '"]',
                                                                $suite));
    });
}

var validatorFixtures = {
    setup: function() {
        $.mockjaxSettings = {
            status: 200,
            responseTime: 0,
            contentType: 'text/json',
            dataType: 'json'
        };
        $("#qunit-fixture").append($("#addon-validator-template").html());
    },
    teardown: function() {
        $.mockjaxClear();
    }
};


module('Validator: Passing Validation', $.extend({}, validatorFixtures));

asyncTest('Test passing', function() {
    var $suite = $('#addon-validator-suite-test'), tiers=[], results=[];

    $.mockjax({
        url: '/validate',
        response: function(settings) {
            this.responseText = {
                "validation": {
                    "errors": 0,
                    "detected_type": "extension",
                    "success": true,
                    "warnings": 0,
                    "notices": 0,
                    "message_tree": {},
                    "messages": [],
                    "rejected": false,
                    "metadata": {
                        "version": "1.3a.20100704",
                        "id": "developer@somewhere.org",
                        "name": "The Add One"
                    }
                }
            };
        }
    });

    $('#addon-validator-suite-test').trigger('validate');

    tests.waitFor(function() {
        return $('[class~="test-tier"][data-tier="1"]', $suite).hasClass(
                                                            'tests-passed');
    }).thenDo(function() {
        pushTiersAndResults(tiers, results);
        $.each(tiers, function(i, tier) {
            var tierN = i+1;
            ok(tier.hasClass('tests-passed'),
                'Checking class: ' + tier.attr('class'));
            equals(tier.hasClass('ajax-loading'), false,
                'Checking class: ' + tier.attr('class'));
            equals($('.tier-summary', tier).text(),
                   '0 errors, 0 warnings');
            // Note: still not sure why there is a period at the end
            // here (even though it's getting cleared)
            equals($('#suite-results-tier-' + tierN.toString() +
                     ' .result-summary').text(),
                   '0 errors, 0 warnings.');
        });
        $.each(results, function(i, result) {
            ok(result.hasClass('tests-passed'),
                'Checking class: ' + result.attr('class'));
            equals(result.hasClass('ajax-loading'), false,
                'Checking class: ' + result.attr('class'));
        });
        equals($('.suite-summary span', $suite).text(),
               'Add-on passed validation.');
        start();
    });
});


module('Validator: Failing Validation', $.extend({}, validatorFixtures));

asyncTest('Test failing', function() {
    var $suite = $('#addon-validator-suite-test'), tiers=[], results=[];

    $.mockjax({
        url: '/validate',
        response: function(settings) {
            this.responseText = {
                "validation": {
                    "errors": 1,
                    "detected_type": "extension",
                    "success": false,
                    "warnings": 1,
                    "notices": 0,
                    "message_tree": {
                        "testcases_targetapplication": {
                            "__messages": [],
                            "__warnings": 1,
                            "__errors": 1,
                            "__notices": 0,
                            "test_targetedapplications": {
                                "invalid_max_version": {
                                    "__messages": ["96dc9924ec4c11df991a001cc4d80ee4"],
                                    "__warnings": 0,
                                    "__errors": 1,
                                    "__notices": 0
                                },
                                "__notices": 0,
                                "missing_seamonkey_installjs": {
                                    "__messages": ["96dca428ec4c11df991a001cc4d80ee4"],
                                    "__warnings": 1,
                                    "__errors": 0,
                                    "__notices": 0
                                },
                                "__warnings": 1,
                                "__errors": 1,
                                "__messages": []
                            }
                        }
                    },
                    "messages": [
                        {
                            "context": null,
                            "description": ["The maximum version that was specified is not an acceptable version number for the Mozilla product that it corresponds with.", "Version \"4.0b2pre\" isn't compatible with {ec8030f7-c20a-464f-9b0e-13a3a9e97384}."],
                            "column": 0,
                            "id": ["testcases_targetapplication", "test_targetedapplications", "invalid_max_version"],
                            "file": "install.rdf",
                            "tier": 1,
                            "message": "Invalid maximum version number",
                            "type": "error",
                            "line": 0,
                            "uid": "afdc9924ec4c11df991a001cc4d80ee4"
                        },
                        {
                            "context": null,
                            "description": "SeaMonkey requires install.js, which was not found. install.rdf indicates that the addon supports SeaMonkey.",
                            "column": 0,
                            "id": ["testcases_targetapplication", "test_targetedapplications", "missing_seamonkey_installjs"],
                            "file": "install.rdf",
                            "tier": 2,
                            "message": "Missing install.js for SeaMonkey.",
                            "type": "warning",
                            "line": 0,
                            "uid": "96dca428ec4c11df991a001cc4d80ee4"
                        }
                    ],
                    "rejected": false,
                    "metadata": {
                        "version": "1.3a.20100704",
                        "id": "developer@somewhere.org",
                        "name": "The Add One"
                    }
                }
            };
        }
    });

    $('#addon-validator-suite-test').trigger('validate');

    tests.waitFor(function() {
        return $('[class~="test-tier"][data-tier="1"]', $suite).hasClass(
                                                            'tests-failed');
    }).thenDo(function() {
        var missingInstall, invalidVer;
        pushTiersAndResults(tiers, results);
        $.each(tiers, function(i, tier) {
            var tierN = i+1;
            equals(tier.hasClass('ajax-loading'), false,
                'Checking class: ' + tier.attr('class'));
            switch (tierN) {
                case 1:
                case 2:
                    ok(tier.hasClass('tests-failed'),
                       'Checking class: ' + tier.attr('class'));
                    break;
                default:
                    ok(tier.hasClass('tests-passed'),
                       'Checking class: ' + tier.attr('class'));
                    break;
            }
        });
        $.each(results, function(i, result) {
            var tierN = i+1;
            equals(result.hasClass('ajax-loading'), false,
                   'Checking class: ' + result.attr('class'));
            switch (tierN) {
                case 1:
                case 2:
                    ok(result.hasClass('tests-failed'),
                       'Checking class: ' + result.attr('class'));
                    break;
                default:
                    ok(result.hasClass('tests-passed'),
                       'Checking class: ' + result.attr('class'));
                    break;
            }
        });
        equals($('#suite-results-tier-1 .result-summary').text(),
               '1 error, 0 warnings.');
        equals($('#suite-results-tier-2 .result-summary').text(),
               '0 errors, 1 warning.');
        missingInstall = $('#v-msg-96dca428ec4c11df991a001cc4d80ee4', $suite);
        equals(missingInstall.length, 1);
        equals(missingInstall.parent().attr('data-tier'), "2",
               "not attached to tier 2");
        equals(missingInstall.attr('class'), 'msg msg-warning');
        equals($('h5', missingInstall).text(),
               'Missing install.js for SeaMonkey.');
        equals($('p', missingInstall).text(),
               'Warning: SeaMonkey requires install.js, which was not ' +
               'found. install.rdf indicates that the addon supports ' +
               'SeaMonkey.');
        installVer = $('#v-msg-afdc9924ec4c11df991a001cc4d80ee4', $suite);
        equals(installVer.length, 1);
        equals(installVer.parent().attr('data-tier'), "1",
               "not attached to tier 1");
        equals(installVer.attr('class'), 'msg msg-error');
        equals($('p', installVer).text(),
               'Error: The maximum version that was specified is not an ' +
               'acceptable version number for the Mozilla product that ' +
               'it corresponds with.Error: Version \"4.0b2pre\" isn\'t ' +
               'compatible with {ec8030f7-c20a-464f-9b0e-13a3a9e97384}.');
        equals($('.suite-summary span', $suite).text(),
               'Add-on failed validation.');
        equals($('#suite-results-tier-4 .tier-results span').text(),
               'All tests passed successfully.');
        start();
    });
});


module('Validator: 500 Error response', $.extend({}, validatorFixtures));

asyncTest('Test 500 error', function() {
    var $suite = $('#addon-validator-suite-test'), tiers=[], results=[];

    $.mockjax({
        url: '/validate',
        status: 500,
        responseText: '500 Internal Error'
    });

    $('#addon-validator-suite-test').trigger('validate');

    tests.waitFor(function() {
        return $('[class~="test-tier"][data-tier="1"]', $suite).hasClass(
                                                            'tests-failed');
    }).thenDo(function() {
        pushTiersAndResults(tiers, results);
        $.each(tiers, function(i, tier) {
            ok(tier.hasClass('tests-failed'),
                'Checking class: ' + tier.attr('class'));
            equals(tier.hasClass('ajax-loading'), false,
                'Checking class: ' + tier.attr('class'));
        });
        $.each(results, function(i, result) {
            ok(result.hasClass('tests-failed'),
                'Checking class: ' + result.attr('class'));
            ok(!result.hasClass('tests-passed'),
                'Should not have this class');
            equals(result.hasClass('ajax-loading'), false,
                'Checking class: ' + result.attr('class'));
        });
        start();
    });
});


module('Validator: Timeout', $.extend({}, validatorFixtures));

asyncTest('Test timeout', function() {
    var $suite = $('#addon-validator-suite-test'), tiers=[], results=[];

    $.mockjax({
        url: '/validate',
        isTimeout: true
    });

    $('#addon-validator-suite-test').trigger('validate');

    tests.waitFor(function() {
        return $('[class~="test-tier"][data-tier="1"]', $suite).hasClass(
                                                            'tests-failed');
    }).thenDo(function() {
        pushTiersAndResults(tiers, results);
        $.each(tiers, function(i, tier) {
            ok(tier.hasClass('tests-failed'),
                'Checking class: ' + tier.attr('class'));
            equals(tier.hasClass('ajax-loading'), false,
                'Checking class: ' + tier.attr('class'));
        });
        $.each(results, function(i, result) {
            ok(result.hasClass('tests-failed'),
                'Checking class: ' + result.attr('class'));
            equals(result.hasClass('ajax-loading'), false,
                'Checking class: ' + result.attr('class'));
        });
        start();
    });
});

module('Validator: task error', $.extend({}, validatorFixtures));

asyncTest('Test task error', function() {
    var $suite = $('#addon-validator-suite-test'), tiers=[], results=[];

    $.mockjax({
        url: '/validate',
        status: 200,
        responseText: {
            "url": "validate",
            "validation": "",
            "upload": "fa8f7dc58a3542d1a34180b72d0f607f",
            "error": "Traceback (most recent call last):\n  File \"/Users/kumar/dev/zamboni/apps/devhub/tasks.py\", line 23, in validator\n    result = _validator(upload)\n  File \"/Users/kumar/dev/zamboni/apps/devhub/tasks.py\", line 49, in _validator\n    import validator.main as addon_validator\n  File \"/Users/kumar/dev/zamboni/vendor/src/amo-validator/validator/main.py\", line 17, in <module>\n    import validator.testcases.l10ncompleteness\n  File \"/Users/kumar/dev/zamboni/vendor/src/amo-validator/validator/testcases/l10ncompleteness.py\", line 3, in <module>\n    import chardet\nImportError: No module named chardet\n"}
    });

    $('#addon-validator-suite-test').trigger('validate');

    tests.waitFor(function() {
        return $('[class~="test-tier"][data-tier="1"]', $suite).hasClass(
                                                            'tests-failed');
    }).thenDo(function() {
        pushTiersAndResults(tiers, results);
        $.each(tiers, function(i, tier) {
            ok(tier.hasClass('tests-failed'),
               'Checking class: ' + tier.attr('class'));
            equals(tier.hasClass('ajax-loading'), false,
                   'Checking class: ' + tier.attr('class'));
        });
        $.each(results, function(i, result) {
            ok(result.hasClass('tests-failed'),
               'Checking class: ' + result.attr('class'));
            ok(!result.hasClass('tests-passed'),
               'Unexpected class: ' + result.attr('class'));
            equals(result.hasClass('ajax-loading'), false,
                   'Checking class: ' + result.attr('class'));
        });
        start();
    });
});

});
