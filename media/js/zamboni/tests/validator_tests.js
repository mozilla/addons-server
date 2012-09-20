$(document).ready(function(){

function pushTiersAndResults($suite, tiers, results) {
    $.each(['1','2','3','4'], function(i, val) {
        tiers.push($('[class~="test-tier"][data-tier="' + val + '"]',
                                                                $suite));
        results.push($('[class~="tier-results"][data-tier="' + val + '"]',
                                                                $suite));
    });
}

var validatorFixtures = {
    setup: function() {
        this.sandbox = tests.createSandbox('#addon-validator-template');
        $.mockjaxSettings = {
            status: 200,
            responseTime: 0,
            contentType: 'text/json',
            dataType: 'json'
        };
        initValidator(this.sandbox);
    },
    teardown: function() {
        this.sandbox.remove();
    }
};


module('Validator: Passing Validation', validatorFixtures);

asyncTest('Test passing', function() {
    var $suite = $('.addon-validator-suite', this.sandbox),
        tiers=[], results=[];

    var mock = $.mockjax({
        url: '/validate',
        response: function(settings) {
            this.responseText = {
                "validation": {
                    "errors": 0,
                    "detected_type": "extension",
                    "success": true,
                    "warnings": 1,
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

    $suite.bind('success.validation', function() {
        pushTiersAndResults($suite, tiers, results);
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
        $.mockjaxClear(mock);
        start();
    });

    $suite.trigger('validate');
});


module('Validator: Failing Validation', validatorFixtures);

asyncTest('Test failing', function() {
    var $suite = $('.addon-validator-suite', this.sandbox),
        tiers=[], results=[];

    var mock = $.mockjax({
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

    $suite.bind('success.validation', function() {
        var missingInstall, invalidVer;
        pushTiersAndResults($suite, tiers, results);
        $.each(tiers, function(i, tier) {
            var tierN = i+1;
            equals(tier.hasClass('ajax-loading'), false,
                'Checking class: ' + tier.attr('class'));
            switch (tierN) {
                case 1:
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
                    ok(result.hasClass('tests-failed'),
                       'Checking class: ' + result.attr('class'));
                    break;
                case 2:
                    ok(result.hasClass('tests-passed-warnings'),
                       'Checking class: ' + result.attr('class'));
                    break;
                default:
                    ok(result.hasClass('tests-passed'),
                       'Checking class: ' + result.attr('class'));
                    break;
            }
        });
        equals($('#suite-results-tier-1 .result-summary', $suite).text(),
               '1 error, 0 warnings');
        equals($('#suite-results-tier-2 .result-summary', $suite).text(),
               '0 errors, 1 warning');
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
        $.mockjaxClear(mock);
        start();
    });

    $suite.trigger('validate');
});

asyncTest('Test error/warning prefix', function() {
    var $suite = $('.addon-validator-suite', this.sandbox);

    var mock = $.mockjax({
        url: '/validate',
        response: function(settings) {
            this.responseText = {
                "validation": {
                    "errors": 1,
                    "detected_type": "extension",
                    "success": false,
                    "warnings": 1,
                    "notices": 0,
                    "message_tree": {},
                    "messages": [
                        {
                            "context": null,
                            "description": ["warning"],
                            "column": 0,
                            "id": [],
                            "file": "file.js",
                            "tier": 1,
                            "message": "some warning",
                            "type": "warning",
                            "line": 0,
                            "uid": "afdc9924ec4c11df991a001cc4d80ee4"
                        },
                        {
                            "context": null,
                            "description": ["error"],
                            "column": 0,
                            "id": [],
                            "file": "file.js",
                            "tier": 1,
                            "message": "some error",
                            "type": "error",
                            "line": 0,
                            "uid": "96dca428ec4c11df991a001cc4d80ee4"
                        },
                        {
                            "context": null,
                            "description": ["notice"],
                            "column": 0,
                            "id": [],
                            "file": "file.js",
                            "tier": 1,
                            "message": "some notice",
                            "type": "notice",
                            "line": 0,
                            "uid": "dddca428ec4c11df991a001cc4d80eb1"
                        }
                    ],
                    "rejected": false,
                    "metadata": {}
                }
            };
        }
    });

    $suite.bind('success.validation', function() {
        equals( $('#v-msg-afdc9924ec4c11df991a001cc4d80ee4 p', $suite).text(),
               'Warning: warning');
        equals( $('#v-msg-96dca428ec4c11df991a001cc4d80ee4 p', $suite).text(),
               'Error: error');
        equals( $('#v-msg-dddca428ec4c11df991a001cc4d80eb1 p', $suite).text(),
               'Warning: notice');
        $.mockjaxClear(mock);
        start();
    });

    $suite.trigger('validate');
});


var compatibilityFixtures = {
    setup: function() {
        this.sandbox = tests.createSandbox('#addon-compatibility-template');
        $.mockjaxSettings = {
            status: 200,
            responseTime: 0,
            contentType: 'text/json',
            dataType: 'json'
        };
        initValidator(this.sandbox);
    },
    teardown: function() {
        this.sandbox.remove();
    }
};

module('Validator: Compatibility', compatibilityFixtures);

asyncTest('Test basic', function() {
    var $suite = $('.addon-validator-suite', this.sandbox),
        tiers=[], results=[];

    var mock = $.mockjax({
        url: '/validate',
        responseText: {
            "url": "/upload/d5d993a5a2fa4b759ae2fa3b2eda2a38/json",
            "full_report_url": "/upload/d5d993a5a2fa4b759ae2fa3b2eda2a38",
            "upload": "d5d993a5a2fa4b759ae2fa3b2eda2a38",
            "error": null,
            "validation": {
                "errors": 0,
                "success": false,
                "warnings": 5,
                "ending_tier": 5,
                "messages": [{
                    "context": null,
                    "description": ["Some non-compatibility warning."],
                    "column": null,
                    "id": ["testcases_packagelayout", "test_blacklisted_files", "disallowed_extension"],
                    "file": "ffmpeg/libmp3lame-0.dll",
                    "tier": 1,
                    "for_appversions": null,
                    "message": "Flagged file extension found",
                    "type": "error",
                    "line": null,
                    "uid": "bb0b38812d8f450a85fa90a2e7e6693b"
                },
                {
                    "context": ["<code>"],
                    "description": ["A dangerous or banned global..."],
                    "column": 23,
                    "id": [],
                    "file": "chrome/content/youtune.js",
                    "tier": 3,
                    "for_appversions": {
                        "{ec8030f7-c20a-464f-9b0e-13a3a9e97384}": ["6.*"]
                    },
                    "message": "Dangerous Global Object",
                    "type": "warning",
                    "line": 533,
                    "uid": "2a96f7faee7a41cca4d6ead26dddc6b3"
                },
                {
                    "context": ["<code>"],
                    "description": ["some other error..."],
                    "column": 23,
                    "id": [],
                    "file": "file.js",
                    "tier": 3,
                    "for_appversions": {
                        "{ec8030f7-c20a-464f-9b0e-13a3a9e97384}": ["6.*"]
                    },
                    "message": "Some error",
                    "type": "error",
                    "line": 533,
                    "uid": "dd96f7faee7a41cca4d6ead26dddc6c2"
                },
                {
                    "context": ["<code>"],
                    "description": "To prevent vulnerabilities...",
                    "column": 2,
                    "id": [],
                    "file": "chrome/content/youtune.js",
                    "tier": 3,
                    "for_appversions": {
                        "{ec8030f7-c20a-464f-9b0e-13a3a9e97384}": ["6.*"]
                    },
                    "message": "on* attribute being set using setAttribute",
                    "type": "notice",
                    "line": 226,
                    "uid": "9a07163bb74e476c96a2bd467a2bbe52"
                },
                {
                    "context": null,
                    "description": "The add-on doesn\'t have...",
                    "column": null,
                    "id": [],
                    "file": "chrome.manifest",
                    "tier": 4,
                    "for_appversions": {
                        "{ec8030f7-c20a-464f-9b0e-13a3a9e97384}": ["6.0a2"]
                    },
                    "message": "Add-on cannot be localized",
                    "type": "notice",
                    "line": null,
                    "uid": "92a0be84024a464e87046b04e26232c4"
                }],
                "detected_type": "extension",
                "notices": 2,
                "message_tree": {},
                "metadata": {}
            }
        }
    });

    $suite.bind('success.validation', function() {
        equals($('#suite-results-tier-errors', $suite).length, 0);
        equals($('.result-header h4:visible', $suite).eq(0).text(),
               'General Tests');
        equals($('.result-header h4:visible', $suite).eq(1).text(),
               'Firefox 6.* Tests');
        equals($('#v-msg-dd96f7faee7a41cca4d6ead26dddc6c2 p:eq(0)', $suite).text(),
               'Error: some other error...');
        ok($('#v-msg-bb0b38812d8f450a85fa90a2e7e6693b', $suite).length == 1,
           'Non-compatibility message should be shown');
        equals($('#suite-results-tier-ec8030f7-c20a-464f-9b0e-13a3a9e97384-6 .result-summary', $suite).text(),
               '1 error, 2 warnings');
        equals($('#suite-results-tier-ec8030f7-c20a-464f-9b0e-13a3a9e97384-6 .version-change-link', $suite).attr('href'),
               '/firefox-6-changes');
        equals($('#suite-results-tier-ec8030f7-c20a-464f-9b0e-13a3a9e97384-60a2 .version-change-link', $suite).length, 0);
        equals($('#suite-results-tier-1 .result-summary', $suite).text(),
               '1 error, 0 warnings');
        $.mockjaxClear(mock);
        start();
    });

    $suite.trigger('validate');
});

asyncTest('Test all passing ok', function() {
    var $suite = $('.addon-validator-suite', this.sandbox);

    var mock = $.mockjax({
        url: '/validate',
        responseText: {
            "url": "/upload/d5d993a5a2fa4b759ae2fa3b2eda2a38/json",
            "full_report_url": "/upload/d5d993a5a2fa4b759ae2fa3b2eda2a38",
            "upload": "d5d993a5a2fa4b759ae2fa3b2eda2a38",
            "error": null,
            "validation": {
                "errors": 0,
                "success": true,
                "warnings": 5,
                "ending_tier": 5,
                "messages": [],
                "detected_type": "extension",
                "notices": 2,
                "message_tree": {},
                "metadata": {}
            }
        }
    });

    $suite.bind('success.validation', function() {
        equals($('.result-header h4:visible', $suite).eq(0).text(),
               'Compatibility Tests');
        tests.hasClass($('#suite-results-tier-1 .tier-results', $suite),
                       'tests-passed');
        $.mockjaxClear(mock);
        start();
    });

    $suite.trigger('validate');
});

asyncTest('Test all passing with warnings', function() {
    var $suite = $('.addon-validator-suite', this.sandbox);

    var mock = $.mockjax({
        url: '/validate',
        responseText: {
            "url": "/upload/d5d993a5a2fa4b759ae2fa3b2eda2a38/json",
            "full_report_url": "/upload/d5d993a5a2fa4b759ae2fa3b2eda2a38",
            "upload": "d5d993a5a2fa4b759ae2fa3b2eda2a38",
            "error": null,
            "validation": {
                "errors": 0,
                "success": true,
                "warnings": 0,
                "ending_tier": 5,
                "compatibility_summary": {
                    "notices": 0,
                    "errors": 0,
                    "warnings": 1
                },
                "messages": [{
                    "context": [null, "(function(){javascript:timelineCreateVideoFrame();", "})()"],
                    "description": "Description...",
                    "column": null,
                    "id": ["testcases_scripting", "_regex_tests", "javascript_data_urls"],
                    "compatibility_type": "warning",
                    "file": "chrome/content/timeline2.html",
                    "tier": 3,
                    "for_appversions": {
                        "{ec8030f7-c20a-464f-9b0e-13a3a9e97384}": ["6.0a1", "6.*", "4.0.*"]
                    },
                    "message": "javascript:/data: URIs may be incompatible with Firefox 6",
                    "type": "notice",
                    "line": 1,
                    "uid": "fcb993744c45416b80bd20a2479f5c86"
                }],
                "detected_type": "extension",
                "notices": 2,
                "message_tree": {},
                "metadata": {}
            }
        }
    });

    $suite.bind('success.validation', function() {
        // 'Compatibility Tests' should be hidden:
        equals($('#suite-results-tier-1:visible', $suite).length, 0);
        $.mockjaxClear(mock);
        start();
    });

    $suite.trigger('validate');
});

asyncTest('Test task error', function() {
    var $suite = $('.addon-validator-suite', this.sandbox),
        tiers=[], results=[];

    var mock = $.mockjax({
        url: '/validate',
        responseText: {
            "url": "/upload/d5d993a5a2fa4b759ae2fa3b2eda2a38/json",
            "full_report_url": "/upload/d5d993a5a2fa4b759ae2fa3b2eda2a38",
            "upload": "d5d993a5a2fa4b759ae2fa3b2eda2a38",
            "error": "Traceback (most recent call last):\n  File \"/Users/kumar/dev/zamboni/apps/devhub/tasks.py\", line 23, in validator\n    result = _validator(upload)\n  File \"/Users/kumar/dev/zamboni/apps/devhub/tasks.py\", line 49, in _validator\n    import validator.main as addon_validator\n  File \"/Users/kumar/dev/zamboni/vendor/src/amo-validator/validator/main.py\", line 17, in <module>\n    import validator.testcases.l10ncompleteness\n  File \"/Users/kumar/dev/zamboni/vendor/src/amo-validator/validator/testcases/l10ncompleteness.py\", line 3, in <module>\n    import chardet\nImportError: No module named chardet\n",
            "validation": ""
        }
    });

    $suite.bind('success.validation', function() {
        equals($('.msg', $suite).text(),
               'ErrorError: Validation task could not complete or ' +
               'completed with errors');
        equals($('.msg:visible', $suite).length, 1);
        $.mockjaxClear(mock);
        start();
    });

    $suite.trigger('validate');
});

asyncTest('Test no tests section', function() {
    var $suite = $('.addon-validator-suite', this.sandbox);

    var mock = $.mockjax({
        url: '/validate',
        responseText: {
            "url": "/upload/d5d993a5a2fa4b759ae2fa3b2eda2a38/json",
            "full_report_url": "/upload/d5d993a5a2fa4b759ae2fa3b2eda2a38",
            "upload": "d5d993a5a2fa4b759ae2fa3b2eda2a38",
            "error": null,
            "validation": {
                "errors": 0,
                "success": false,
                "warnings": 1,
                "ending_tier": 5,
                "messages": [{
                    "context": ["<code>"],
                    "description": ["A dangerous or banned global..."],
                    "column": 23,
                    "id": [],
                    "file": "chrome/content/youtune.js",
                    "tier": 3,
                    "for_appversions": {
                        "{ec8030f7-c20a-464f-9b0e-13a3a9e97384}": ["6.*"]
                    },
                    "message": "Dangerous Global Object",
                    "type": "error",
                    "line": 533,
                    "uid": "2a96f7faee7a41cca4d6ead26dddc6b3"
                }],
                "detected_type": "extension",
                "notices": 2,
                "message_tree": {},
                "metadata": {}
            }
        }
    });

    $suite.bind('success.validation', function() {
        equals($('#suite-results-tier-1:visible', $suite).length, 0);
        equals($('#suite-results-tier-2:visible', $suite).length, 0);
        equals($('#suite-results-tier-3:visible', $suite).length, 0);
        equals($('#suite-results-tier-4:visible', $suite).length, 0);
        equals($('#suite-results-tier-5:visible', $suite).length, 0);
        equals($('#suite-results-tier-ec8030f7-c20a-464f-9b0e-13a3a9e97384-6 .msg', $suite).length, 1);
        $.mockjaxClear(mock);
        start();
    });

    $suite.trigger('validate');
});

asyncTest('Test compat error override', function() {
    var $suite = $('.addon-validator-suite', this.sandbox),
        tiers=[], results=[];

    var mock = $.mockjax({
        url: '/validate',
        responseText: {
            "url": "/upload/d5d993a5a2fa4b759ae2fa3b2eda2a38/json",
            "full_report_url": "/upload/d5d993a5a2fa4b759ae2fa3b2eda2a38",
            "upload": "d5d993a5a2fa4b759ae2fa3b2eda2a38",
            "error": null,
            "validation": {
                "errors": 0,
                "compatibility_summary": {"errors": 1},
                "success": false,
                "warnings": 1,
                "ending_tier": 5,
                "messages": [{
                    "context": ["<code>"],
                    "description": ["A dangerous or banned global..."],
                    "column": 23,
                    "id": [],
                    "file": "chrome/content/youtune.js",
                    "tier": 3,
                    "for_appversions": {
                        "{ec8030f7-c20a-464f-9b0e-13a3a9e97384}": ["6.*"]
                    },
                    "message": "Dangerous Global Object",
                    "type": "warning",
                    "compatibility_type": "error",
                    "line": 533,
                    "uid": "2a96f7faee7a41cca4d6ead26dddc6b3"
                }],
                "detected_type": "extension",
                "notices": 0,
                "message_tree": {},
                "metadata": {}
            }
        }
    });

    $suite.bind('success.validation', function() {
        var $msg = $('#suite-results-tier-ec8030f7-c20a-464f-9b0e-13a3a9e97384-6 .msg', $suite);
        ok($msg.hasClass('msg-error'),
           'Expected msg-error, got: ' + $msg.attr('class'));
        $.mockjaxClear(mock);
        start();
    });

    $suite.trigger('validate');
});

asyncTest('Test basic error override', function() {
    var $suite = $('.addon-validator-suite', this.sandbox),
        tiers=[], results=[];

    var mock = $.mockjax({
        url: '/validate',
        responseText: {
            "url": "/upload/d5d993a5a2fa4b759ae2fa3b2eda2a38/json",
            "full_report_url": "/upload/d5d993a5a2fa4b759ae2fa3b2eda2a38",
            "upload": "d5d993a5a2fa4b759ae2fa3b2eda2a38",
            "error": null,
            "validation": {
                "errors": 0,
                "compatibility_summary": {"errors": 1},
                "success": false,
                "warnings": 1,
                "ending_tier": 5,
                "messages": [{
                    "context": ["<code>"],
                    "description": ["Contains binary components..."],
                    "column": 23,
                    "id": [],
                    "file": "chrome/content/youtune.dll",
                    "tier": 1,
                    "for_appversions": null,
                    "message": "Contains Binary Components",
                    "type": "warning",
                    "compatibility_type": "error",
                    "line": 533,
                    "uid": "2a96f7faee7a41cca4d6ead26dddc6b3"
                }],
                "detected_type": "extension",
                "notices": 0,
                "message_tree": {},
                "metadata": {}
            }
        }
    });

    $suite.bind('success.validation', function() {
        var $msg = $('#suite-results-tier-1 .msg', $suite);
        ok($msg.hasClass('msg-error'),
           'Expected msg-error, got: ' + $msg.attr('class'));
        $.mockjaxClear(mock);
        start();
    });

    $suite.trigger('validate');
});

asyncTest('Test single tier', function() {
    var $suite = $('.addon-validator-suite', this.sandbox),
        tiers=[], results=[];

    var mock = $.mockjax({
        url: '/validate',
        responseText: {
            "url": "/upload/d5d993a5a2fa4b759ae2fa3b2eda2a38/json",
            "full_report_url": "/upload/d5d993a5a2fa4b759ae2fa3b2eda2a38",
            "upload": "d5d993a5a2fa4b759ae2fa3b2eda2a38",
            "error": null,
            "validation": {
                "errors": 0,
                "success": false,
                "warnings": 5,
                "compatibility_summary": {
                    "notices": 1,
                    "errors": 2,
                    "warnings": 0
                },
                "ending_tier": 5,
                "messages": [{
                    "context": null,
                    "compatibility_type": "error",
                    "uid": "bc73cbff60534798b46ed5840d1544c6",
                    "column": null,
                    "line": null,
                    "file": "",
                    "tier": 5,
                    "for_appversions": {
                        "{ec8030f7-c20a-464f-9b0e-13a3a9e97384}": ["4.2a1pre", "5.0a2", "6.*", "4.0.*"]
                    },
                    "message": "Firefox 5 Compatibility Detected",
                    "type": "error",
                    "id": ["testcases_compatibility", "firefox_5_test", "fx5_notice"],
                    "description": "Potential compatibility for FX5 was detected."
                }],
                "detected_type": "extension",
                "notices": 2,
                "message_tree": {},
                "metadata": {}
            }
        }
    });

    $suite.bind('success.validation', function() {
        // This was failing with tier not found
        equals($('#suite-results-tier-ec8030f7-c20a-464f-9b0e-13a3a9e97384-6 .msg', $suite).length, 1);
        $.mockjaxClear(mock);
        start();
    });

    $suite.trigger('validate');
});

asyncTest('Test no compat tests', function() {
    var $suite = $('.addon-validator-suite', this.sandbox),
        tiers=[], results=[];

    var mock = $.mockjax({
        url: '/validate',
        responseText: {
            "url": "/upload/d5d993a5a2fa4b759ae2fa3b2eda2a38/json",
            "full_report_url": "/upload/d5d993a5a2fa4b759ae2fa3b2eda2a38",
            "upload": "d5d993a5a2fa4b759ae2fa3b2eda2a38",
            "error": null,
            "validation": {
                "errors": 1,
                "success": false,
                "warnings": 7,
                "compatibility_summary": {
                    "notices": 0,
                    "errors": 0,
                    "warnings": 0
                },
                "ending_tier": 5,
                "messages": [{
                    "context": null,
                    "description": ["Non-compat error."],
                    "column": null,
                    "compatibility_type": null,
                    "file": "components/cooliris.dll",
                    "tier": 1,
                    "for_appversions": null,
                    "message": "Some error",
                    "type": "error",
                    "line": null,
                    "uid": "6fd1f5c74c4445f79a1919c8480e4e72"
                }],
                "detected_type": "extension",
                "notices": 2,
                "message_tree": {},
                "metadata": {}
            }
        }
    });

    $suite.bind('success.validation', function() {
        // template is hidden
        equals($('.template .result:visible', $suite).length, 0);
        // The non-compat error exists
        equals($('#v-msg-6fd1f5c74c4445f79a1919c8480e4e72', $suite).length, 1);
        $.mockjaxClear(mock);
        start();
    });

    $suite.trigger('validate');
});

asyncTest('Test compat ignores non-compat warnings and notices', function() {
    var $suite = $('.addon-validator-suite', this.sandbox);

    var mock = $.mockjax({
        url: '/validate',
        responseText: {
            "url": "/upload/d5d993a5a2fa4b759ae2fa3b2eda2a38/json",
            "full_report_url": "/upload/d5d993a5a2fa4b759ae2fa3b2eda2a38",
            "upload": "d5d993a5a2fa4b759ae2fa3b2eda2a38",
            "error": null,
            "validation": {
                "errors": 0,
                "compatibility_summary": {"errors": 1},
                "success": false,
                "warnings": 1,
                "ending_tier": 5,
                "messages": [{
                    "context": ["<code>"],
                    "description": ["A dangerous or banned global..."],
                    "column": 23,
                    "id": [],
                    "file": "chrome/content/youtune.js",
                    "tier": 3,
                    "for_appversions": {
                        "{ec8030f7-c20a-464f-9b0e-13a3a9e97384}": ["6.*"]
                    },
                    "message": "Dangerous Global Object",
                    "type": "warning",
                    "compatibility_type": "error",
                    "line": 533,
                    "uid": "2a96f7faee7a41cca4d6ead26dddc6b3"
                }, {
                    "context": ["<code>"],
                    "description": ["Suspicious code..."],
                    "column": 23,
                    "id": [],
                    "file": "chrome/content/youtune.js",
                    "tier": 3,
                    "for_appversions": {
                        "{ec8030f7-c20a-464f-9b0e-13a3a9e97384}": ["6.*"]
                    },
                    "message": "This code may or may not be compatible",
                    "type": "warning",
                    "compatibility_type": "warning",
                    "line": 533,
                    "uid": "1c96f7faee7a41cca4d6ead26dddc6dd"
                }, {
                    "context": ["<code>"],
                    "description": ["Some warning..."],
                    "column": 23,
                    "id": [],
                    "file": "chrome/content/youtune.js",
                    "tier": 3,
                    "for_appversions": null,
                    "message": "Some warning",
                    "type": "warning",
                    "compatibility_type": null,
                    "line": 533,
                    "uid": "1dc6f7faee7a41cca4d6ead26dddceed"
                }, {
                    "context": ["<code>"],
                    "description": ["Some notice..."],
                    "column": 23,
                    "id": [],
                    "file": "chrome/content/youtune.js",
                    "tier": 3,
                    "for_appversions": null,
                    "message": "Some notice",
                    "type": "notice",
                    "compatibility_type": null,
                    "line": 533,
                    "uid": "dce6f7faee7a41cca4d6ead26dddc2c1"
                }, {
                    "context": ["<code>"],
                    "description": ["Some error..."],
                    "column": 23,
                    "id": [],
                    "file": "chrome/content/youtune.js",
                    "tier": 3,
                    "for_appversions": null,
                    "message": "Some error",
                    "type": "error",
                    "compatibility_type": null,
                    "line": 533,
                    "uid": "6cd6f7faee7a41cca4d6ead26dddca4c"
                }],
                "detected_type": "extension",
                "notices": 0,
                "message_tree": {},
                "metadata": {}
            }
        }
    });

    $suite.bind('success.validation', function() {
        // Compat error:
        equals($('#v-msg-2a96f7faee7a41cca4d6ead26dddc6b3', $suite).length, 1);
        // Compat warning:
        equals($('#v-msg-1c96f7faee7a41cca4d6ead26dddc6dd', $suite).length, 1);
        // Regular notice:
        equals($('#v-msg-1dc6f7faee7a41cca4d6ead26dddceed', $suite).length, 0);
        equals($('#v-msg-dce6f7faee7a41cca4d6ead26dddc2c1', $suite).length, 0);
        // Regular error
        equals($('#v-msg-6cd6f7faee7a41cca4d6ead26dddca4c', $suite).length, 1);
        equals($('#suite-results-tier-ec8030f7-c20a-464f-9b0e-13a3a9e97384-6 .result-summary', $suite).text(),
               '1 error, 1 warning');
        equals($('#suite-results-tier-3 .result-summary', $suite).text(),
               '1 error, 0 warnings');
        $.mockjaxClear(mock);
        start();
    });

    $suite.trigger('validate');
});

asyncTest('Test only show errors for targeted app/version', function() {
    var $suite = $('.addon-validator-suite', this.sandbox),
        tiers=[], results=[];

    var mock = $.mockjax({
        url: '/validate',
        responseText: {
            "url": "/upload/d5d993a5a2fa4b759ae2fa3b2eda2a38/json",
            "full_report_url": "/upload/d5d993a5a2fa4b759ae2fa3b2eda2a38",
            "upload": "d5d993a5a2fa4b759ae2fa3b2eda2a38",
            "error": null,
            "validation": {
                "errors": 0,
                "compatibility_summary": {"errors": 1},
                "success": false,
                "warnings": 1,
                "ending_tier": 5,
                "messages": [{
                    "context": ["<code>"],
                    "description": ["Contains binary components..."],
                    "column": 23,
                    "id": [],
                    "file": "chrome/content/youtune.dll",
                    "tier": 1,
                    "for_appversions": {
                        "{ec8030f7-c20a-464f-9b0e-13a3a9e97384}": ["4.2a1pre", "4.49.*", "5.0a2", "5.*", "6.0a1", "6.*"]
                    },
                    "message": "Contains Binary Components",
                    "type": "warning",
                    "compatibility_type": "error",
                    "line": 533,
                    "uid": "2a96f7faee7a41cca4d6ead26dddc6b3"
                }],
                "detected_type": "extension",
                "notices": 0,
                "message_tree": {},
                "metadata": {}
            }
        }
    });

    $suite.bind('success.validation', function() {
        equals($('.result-header h4:visible', $suite).eq(0).text(),
               'Firefox 6.0a1 Tests');
        $.mockjaxClear(mock);
        start();
    });

    $suite.trigger('validate');
});


module('Validator: Incomplete', validatorFixtures);

asyncTest('Test incomplete validation', function() {
    var $suite = $('.addon-validator-suite', this.sandbox),
        tiers=[], results=[];

    var mock = $.mockjax({
        url: '/validate',
        response: function(settings) {
            this.responseText = {
                "url": "/upload/d5d993a5a2fa4b759ae2fa3b2eda2a38/json",
                "full_report_url": "/upload/d5d993a5a2fa4b759ae2fa3b2eda2a38",
                "validation": {
                    "errors": 1,
                    "success": false,
                    "warnings": 0,
                    "ending_tier": 1,
                    "messages": [{
                        "context": null,
                        "description": "",
                        "column": 0,
                        "line": 0,
                        "file": "",
                        "tier": 1,
                        "message": "The XPI could not be opened.",
                        "type": "error",
                        "id": ["main", "test_package", "unopenable"],
                        "uid": "436fd18fb1b24ab6ae950ef18519c90d"
                    }],
                    "rejected": false,
                    "detected_type": "unknown",
                    "notices": 0,
                    "message_tree": {},
                    "metadata": {}
                },
                "upload": "d5d993a5a2fa4b759ae2fa3b2eda2a38",
                "error": null
            };
        }
    });

    $suite.bind('success.validation', function() {
        var missingInstall, invalidVer;
        pushTiersAndResults($suite, tiers, results);
        $.each(tiers, function(i, tier) {
            var tierN = i+1;
            tests.lacksClass(tier, 'ajax-loading');
            switch (tierN) {
                case 1:
                    tests.hasClass(tier, 'tests-failed');
                    break;
                default:
                    tests.hasClass(tier, 'tests-notrun');
                    break;
            }
        });
        $.each(results, function(i, result) {
            var tierN = i+1;
            tests.lacksClass(result, 'ajax-loading');
            switch (tierN) {
                case 1:
                    tests.hasClass(result, 'tests-failed');
                    break;
                default:
                    tests.hasClass(result, 'tests-notrun');
                    break;
            }
        });
        equals($('#suite-results-tier-1 .result-summary', $suite).text(),
               '1 error, 0 warnings');
        equals($('#suite-results-tier-2 .result-summary', $suite).html(),
               '&nbsp;');
        $.mockjaxClear(mock);
        start();
    });

    $suite.trigger('validate');
});


module('Validator: 500 Error response', validatorFixtures);

asyncTest('Test 500 error', function() {
    var $suite = $('.addon-validator-suite', this.sandbox),
        tiers=[], results=[];

    var mock = $.mockjax({
        url: '/validate',
        status: 500,
        responseText: '500 Internal Error'
    });

    $suite.bind('badresponse.validation', function() {
        pushTiersAndResults($suite, tiers, results);
        // First tier should have an internal server error,
        // the other tiers should not have run.
        $.each(tiers, function(i, tier) {
            tests.lacksClass(tier, 'ajax-loading');
            tests.lacksClass(tier, 'tests-passed');
            if (i == 0) {
                tests.hasClass(tier, 'tests-failed');
            } else {
                tests.hasClass(tier, 'tests-notrun');
            }
        });
        $.each(results, function(i, result) {
            tests.lacksClass(result, 'ajax-loading');
            tests.lacksClass(result, 'tests-passed');
            if (i == 0) {
                tests.hasClass(result, 'tests-failed');
            } else {
                tests.hasClass(result, 'tests-notrun');
            }
        });
        $.mockjaxClear(mock);
        start();
    });

    $suite.trigger('validate');
});


// TODO(Kumar) uncomment when bug 706602 is fixed
// module('Validator: Timeout', validatorFixtures);
//
// asyncTest('Test timeout', function() {
//     var $suite = $('.addon-validator-suite', this.sandbox),
//         tiers=[], results=[];
//
//     var mock = $.mockjax({
//         url: '/validate',
//         isTimeout: true
//     });
//
//     $suite.bind('badresponse.validation', function() {
//         pushTiersAndResults($suite, tiers, results);
//         // Firs tier should show the timeout error, other tiers did not run.
//         $.each(tiers, function(i, tier) {
//             tests.lacksClass(tier, 'ajax-loading');
//             if (i == 0) {
//                 tests.hasClass(tier, 'tests-failed');
//             } else {
//                 tests.hasClass(tier, 'tests-notrun');
//             }
//         });
//         $.each(results, function(i, result) {
//             tests.lacksClass(result, 'ajax-loading');
//             if (i == 0) {
//                 tests.hasClass(result, 'tests-failed');
//             } else {
//                 tests.hasClass(result, 'tests-notrun');
//             }
//         });
//         $.mockjaxClear(mock);
//         start();
//     });
//
//     $suite.trigger('validate');
// });

module('Validator: task error', validatorFixtures);

asyncTest('Test task error', function() {
    var $suite = $('.addon-validator-suite', this.sandbox),
        tiers=[], results=[];

    var mock = $.mockjax({
        url: '/validate',
        status: 200,
        responseText: {
            "url": "validate",
            "validation": "",
            "upload": "fa8f7dc58a3542d1a34180b72d0f607f",
            "error": "Traceback (most recent call last):\n  File \"/Users/kumar/dev/zamboni/apps/devhub/tasks.py\", line 23, in validator\n    result = _validator(upload)\n  File \"/Users/kumar/dev/zamboni/apps/devhub/tasks.py\", line 49, in _validator\n    import validator.main as addon_validator\n  File \"/Users/kumar/dev/zamboni/vendor/src/amo-validator/validator/main.py\", line 17, in <module>\n    import validator.testcases.l10ncompleteness\n  File \"/Users/kumar/dev/zamboni/vendor/src/amo-validator/validator/testcases/l10ncompleteness.py\", line 3, in <module>\n    import chardet\nImportError: No module named chardet\n"}
    });

    $suite.bind('success.validation', function() {
        pushTiersAndResults($suite, tiers, results);
        // First tier should show internal error, other tiers should not run.
        $.each(tiers, function(i, tier) {
            tests.lacksClass(tier, 'ajax-loading');
            if (i == 0) {
                tests.hasClass(tier, 'tests-failed');
            } else {
                tests.hasClass(tier, 'tests-notrun');
            }
        });
        $.each(results, function(i, result) {
            tests.lacksClass(result, 'ajax-loading');
            if (i == 0) {
                tests.hasClass(result, 'tests-failed');
            } else {
                tests.hasClass(result, 'tests-notrun');
            }
        });
        $.mockjaxClear(mock);
        start();
    });

    $suite.trigger('validate');
});

module('Validator: support html', validatorFixtures);

asyncTest('Test html', function() {
    var $suite = $('.addon-validator-suite', this.sandbox), err;

    var mock = $.mockjax({
        url: '/validate',
        status: 200,
        response: function(settings) {
            this.responseText = {
                "validation": {
                    "errors": 1,
                    "success": false,
                    "warnings": 0,
                    "ending_tier": 3,
                    "messages": [{
                        "context": null,
                        "description": "The values supplied for &lt;em:id&gt; in the install.rdf file is not a valid UUID string.",
                        "column": 0,
                        "line": 0,
                        "file": "install.rdf",
                        "tier": 1,
                        "message": "The value of &lt;em:id&gt; is invalid.",
                        "type": "error",
                        "id": ["testcases_installrdf", "_test_id", "invalid"],
                        "uid": "3793e550026111e082c3c42c0301fe38"
                    }],
                    "rejected": false,
                    "detected_type": "extension",
                    "notices": 0,
                    "metadata": {
                        "version": "2",
                        "name": "OddNodd",
                        "id": "oddnoddd"
                    }
                }
            };
        }
    });

    $suite.bind('success.validation', function() {
        err = $('#v-msg-3793e550026111e082c3c42c0301fe38', $suite);
        equals($('h5', err).text(),
               'The value of <em:id> is invalid.');
        equals($('p', err).text(),
               'Error: The values supplied for <em:id> in the install.rdf file is not a valid UUID string.');
        $.mockjaxClear(mock);
        start();
    });

    $suite.trigger('validate');
});

module('Validator: error summaries', validatorFixtures);

asyncTest('Test errors are brief', function() {
    var $suite = $('.addon-validator-suite', this.sandbox);

    var mock = $.mockjax({
        url: '/validate',
        status: 200,
        response: function(settings) {
            this.responseText = {
                "validation": {
                    "errors": 1,
                    "success": true,
                    "warnings": 0,
                    "ending_tier": 0,
                    "messages": [{
                        "context": null,
                        "description": "",
                        "column": 0,
                        "line": 0,
                        "file": "",
                        "tier": 1,
                        "message": "Unable to open XPI.",
                        "type": "error",
                        "id": ["main", "test_search"],
                        "uid": "dd5dab88026611e082c3c42c0301fe38"
                    }],
                    "rejected": false,
                    "detected_type": "search",
                    "notices": 0,
                    "message_tree": {},
                    "metadata": {}
                }
            };
        }
    });

    $suite.bind('success.validation', function() {
        equals($('[class~="msg-error"] h5', $suite).text(),
               'Unable to open XPI.');
        equals($('[class~="msg-error"] p', $suite).html(), '&nbsp;');
        $.mockjaxClear(mock);
        start();
    });

    $suite.trigger('validate');
});

module('Validator: code context', validatorFixtures);

asyncTest('Test code context', function() {
    var $suite = $('.addon-validator-suite', this.sandbox);

    var mock = $.mockjax({
        url: '/validate',
        status: 200,
        response: function(settings) {
            this.responseText = {
                "url": "/upload/",
                "full_report_url": "/upload/14bd1cb1ae0d4b11b86395b1a0da7058",
                "validation": {
                    "errors": 0,
                    "success": false,
                    "warnings": 1,
                    "ending_tier": 3,
                    "messages": [{
                        "context": ["&lt;baddddddd html garbage=#&#34;&#34;",
                                    "&lt;foozer&gt;", null],
                        "description": [
                            "There was an error parsing the markup document.",
                            "malformed start tag, at line 1, column 26"],
                        "column": 0,
                        "line": 2,
                        "file": "chrome/content/down.html",
                        "tier": 2,
                        "message": "Markup parsing error",
                        "type": "warning",
                        "id": ["testcases_markup_markuptester",
                               "_feed", "parse_error"],
                        "uid": "bb9948b604b111e09dfdc42c0301fe38"
                    }],
                    "rejected": false,
                    "detected_type": "extension",
                    "notices": 0
                },
                "upload": "14bd1cb1ae0d4b11b86395b1a0da7058",
                "error": null
            };
        }
    });

    $suite.bind('success.validation', function() {
        equals($('.context .file', $suite).text(),
               'chrome/content/down.html');
        equals($('.context .lines div:eq(0)', $suite).text(), '1');
        equals($('.context .lines div:eq(1)', $suite).text(), '2');
        equals($('.context .lines div:eq(2)', $suite).text(), "");
        equals($('.context .inner-code div:eq(0)', $suite).html(),
               '&lt;baddddddd html garbage=#""');
        equals($('.context .inner-code div:eq(1)', $suite).html(),
               '&lt;foozer&gt;');
        equals($('.context .inner-code div:eq(2)', $suite).html(), null);
        $.mockjaxClear(mock);
        start();
    });

    $suite.trigger('validate');
});

asyncTest('Test code context (single line)', function() {
    var $suite = $('.addon-validator-suite', this.sandbox);

    var mock = $.mockjax({
        url: '/validate',
        status: 200,
        response: function(settings) {
            this.responseText = {
                "url": "/upload/",
                "full_report_url": "/upload/14bd1cb1ae0d4b11b86395b1a0da7058",
                "validation": {
                    "errors": 0,
                    "success": false,
                    "warnings": 1,
                    "ending_tier": 3,
                    "messages": [{
                        "context": [null, "foo", null],
                        "description": ["test error"],
                        "column": 0,
                        "line": 1,
                        "file": "chrome/content/down.html",
                        "tier": 2,
                        "message": "Markup parsing error",
                        "type": "warning",
                        "id": ["testcases_markup_markuptester",
                               "_feed", "parse_error"],
                        "uid": "bb9948b604b111e09dfdc42c0301fe38"
                    }],
                    "rejected": false,
                    "detected_type": "extension",
                    "notices": 0
                },
                "upload": "14bd1cb1ae0d4b11b86395b1a0da7058",
                "error": null
            };
        }
    });

    $suite.bind('success.validation', function() {
        equals($('.context .file', $suite).text(),
               'chrome/content/down.html');
        equals($('.context .lines div:eq(0)', $suite).text(), '1');
        equals($('.context .lines div:eq(1)', $suite).text(), '');
        equals($('.context .inner-code div:eq(0)', $suite).html(), 'foo');
        equals($('.context .inner-code div:eq(1)', $suite).html(), null);
        $.mockjaxClear(mock);
        start();
    });

    $suite.trigger('validate');
});


module('Validator: minimal code context', validatorFixtures);

asyncTest('Test code context', function() {
    var $suite = $('.addon-validator-suite', this.sandbox);

    var mock = $.mockjax({
        url: '/validate',
        status: 200,
        response: function(settings) {
            this.responseText = {
                "url": "/upload/",
                "full_report_url": "/upload/14bd1cb1ae0d4b11b86395b1a0da7058",
                "validation": {
                    "errors": 0,
                    "success": false,
                    "warnings": 1,
                    "ending_tier": 3,
                    "messages": [{
                        "context": null,
                        "description": ["Error in install.rdf"],
                        "column": 0,
                        "line": 1,
                        "file": ["silvermelxt_1.3.5.xpi",
                                 "chrome/silvermelxt.jar", "install.rdf",
                                 null],
                        "tier": 2,
                        "message": "Some error",
                        "type": "warning",
                        "id": [],
                        "uid": "bb9948b604b111e09dfdc42c0301fe38"
                    }],
                    "rejected": false,
                    "detected_type": "extension",
                    "notices": 0
                },
                "upload": "14bd1cb1ae0d4b11b86395b1a0da7058",
                "error": null
            };
        }
    });

    $suite.bind('success.validation', function() {
        equals($('.context .file', $suite).text(),
               'silvermelxt_1.3.5.xpi/chrome/silvermelxt.jar/install.rdf');
        $.mockjaxClear(mock);
        start();
    });

    $suite.trigger('validate');
});


module('Validator: code indentation', validatorFixtures);

asyncTest('Test code indentation', function() {
    var $suite = $('.addon-validator-suite', this.sandbox);

    var mock = $.mockjax({
        url: '/validate',
        status: 200,
        response: function(settings) {
            this.responseText = {
                "url": "/upload/",
                "full_report_url": "/upload/14bd1cb1ae0d4b11b86395b1a0da7058",
                "validation": {
                    "errors": 0,
                    "success": false,
                    "warnings": 1,
                    "ending_tier": 3,
                    "messages": [{
                        "context": [
                            "                    if(blah) {",
                            "                        setTimeout(blah);",
                            "                    }"],
                        "description": ["Dangerous global in somefile.js"],
                        "column": 0,
                        "line": 1,
                        "file": ["silvermelxt_1.3.5.xpi",
                                 "chrome/silvermelxt.jar", "somefile.js"],
                        "tier": 2,
                        "message": "Some error",
                        "type": "warning",
                        "id": [],
                        "uid": "bb9948b604b111e09dfdc42c0301fe38"
                    }, {
                        "context": ["foobar"],
                        "description": ["Something in somefile.js"],
                        "column": 0,
                        "line": 1,
                        "file": ["silvermelxt_1.3.5.xpi",
                                 "/path/to/somefile.js"],
                        "tier": 2,
                        "message": "Some error",
                        "type": "warning",
                        "id": [],
                        "uid": "dd5448b604b111e09dfdc42c0301fe38"
                    }],
                    "rejected": false,
                    "detected_type": "extension",
                    "notices": 0
                },
                "upload": "14bd1cb1ae0d4b11b86395b1a0da7058",
                "error": null
            };
        }
    });

    $suite.bind('success.validation', function() {
        equals($('.context .file:eq(0)', $suite).text(),
               'silvermelxt_1.3.5.xpi/chrome/silvermelxt.jar/somefile.js');
        equals($('.context .inner-code div:eq(0)', $suite).html(),
               'if(blah) {');
        equals($('.context .inner-code div:eq(1)', $suite).html(),
               '&nbsp;&nbsp;&nbsp;&nbsp;setTimeout(blah);');
        equals($('.context .file:eq(1)', $suite).text(),
               'silvermelxt_1.3.5.xpi/path/to/somefile.js');
        $.mockjaxClear(mock);
        start();
    });

    $suite.trigger('validate');
});


module('Validator: counts', validatorFixtures);

asyncTest('error/warning count', function() {
    var $suite = $('.addon-validator-suite', this.sandbox);

    var mock = $.mockjax({
        url: '/validate',
        status: 200,
        response: function(settings) {
            this.responseText = {
                "error": null,
                "validation": {
                    "errors": 0,
                    "success": false,
                    "warnings": 1,
                    "ending_tier": 3,
                    "messages": [
                        {"tier": 1, "type": "warning", "uid": "a1"},
                        {"tier": 1, "type": "notice", "uid": "a2"},
                        {"tier": 1, "type": "notice", "uid": "a3"}
                    ],
                    "notices": 2
                }
            }
        }
    });

    $suite.bind('success.validation', function() {
        equals($('[class~="test-tier"][data-tier="1"] .tier-summary').text(),
               '0 errors, 3 warnings');
        equals($('#suite-results-tier-1 .result-summary').text(),
               '0 errors, 3 warnings.');
        $.mockjaxClear(mock);
        start();
    });

    $suite.trigger('validate');
});

});
