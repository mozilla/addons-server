$(document).ready(function() {

    if ($('.addon-validator-suite').length) {
        initValidator();
    }

});

function initValidator($doc) {
    $doc = $doc || $(document);

    function inherit(OtherClass, constructor) {
        var NewClass = function() {
            OtherClass.apply(this, arguments);
            if (typeof constructor !== 'undefined') {
                constructor.apply(this, arguments);
            }
        }
        $.extend(NewClass.prototype, OtherClass.prototype);
        return NewClass;
    }

    function emptyFn() {
        return null;
    }

    function ResultsTier($suite, tierId, options) {
        if (typeof options === 'undefined')
            options = {}
        if (typeof options.app === 'undefined')
            options.app = null;
        if (typeof options.testsWereRun === 'undefined')
            options.testsWereRun = true;
        this.$results = $('.results', $suite);
        this.app = options.app;
        this.testsWereRun = options.testsWereRun;
        this.counts = {error: 0, warning: 0};
        this.tierId = tierId;
        this.$suite = $suite;
        this.$dom = $('#suite-results-tier-' + tierId, $suite);
        if (!this.$dom.length) {
            this.$dom = this.createDom();
            this.$results.append(this.$dom);
        }
        this.$tierResults = $('.tier-results', this.$dom);
        this.wakeUp();
    }

    ResultsTier.prototype.tallyMsgType = function(type_) {
        if (type_ == 'notice') type_ = 'warning';
        this.counts[type_] += 1;
    };

    ResultsTier.prototype.createDom = function() {
        var $tier = $($('.template', this.$suite).html());
        $tier.attr('id', 'suite-results-tier-' + this.tierId);
        return $tier;
    }

    ResultsTier.prototype.summarize = function() {
        var sm = resultSummary(this.counts.error, this.counts.warning, this.testsWereRun),
            resultClass, summaryMsg;
        $('.result-summary', this.$dom).css('visibility', 'visible')
                                       .empty().text(sm);
        if (this.counts.error) {
            resultClass = 'tests-failed';
        } else if (this.counts.warning) {
            resultClass = 'tests-passed-warnings';
        } else {
            if (this.testsWereRun) {
                summaryMsg = gettext('All tests passed successfully.');
                resultClass = 'tests-passed';
            } else {
                summaryMsg = gettext('These tests were not run.');
                resultClass = 'tests-notrun';
                // No summary since no tests were run:
                $('.result-summary', this.$dom).html('&nbsp;');
            }
            this.$tierResults.append('<span>' + summaryMsg + '</span>');
        }
        this.$tierResults.removeClass('ajax-loading', 'tests-failed',
                                      'tests-passed', 'tests-passed-warnings',
                                      'tests-notrun')
                         .addClass(resultClass);
        if ($('.test-tier', this.$suite).length)
            this.topSummary();
        return this.counts;
    };

    ResultsTier.prototype.topSummary = function() {
        var $top = $('[class~="test-tier"]' +
                     '[data-tier="' + this.tierId + '"]', this.$suite),
            summaryMsg = resultSummary(this.counts.error, this.counts.warning, this.testsWereRun);

        $('.tier-summary', $top).text(summaryMsg);
        $top.removeClass('ajax-loading', 'tests-failed', 'tests-passed',
                         'tests-notrun');
        if (this.counts.error > 0) {
            $top.addClass('tests-failed');
        } else {
            if (this.testsWereRun)
                $top.addClass('tests-passed');
            else
                $top.addClass('tests-notrun');
        }
    };

    ResultsTier.prototype.wakeUp = function() {
        var $title = $('h4', this.$dom),
            changeLink;
        $('.tier-results', this.$dom).empty();
        this.$dom.removeClass('hidden');
        this.$dom.show();
        if (this.app) {
            // Override the title with a special app/version title
            $title.text(format('{0} {1} {2}',
                               this.app.trans[this.app.guid],
                               this.app.version,
                               gettext('Tests')));
            changeLink = this.app.versionChangeLinks[this.app.guid + ' ' +
                                                     this.app.version];
            if (changeLink) {
                this.$dom.prepend(
                    format('<a class="version-change-link" href="{0}">{1}</a>',
                           changeLink,
                           // L10n: Example: Changes in Firefox 5
                           gettext(format('Changes in {0} {1}',
                                          this.app.trans[this.app.guid],
                                          /\d+/.exec(this.app.version)))));
            }
        } else if (!$title.text()) {
            $title.text(gettext('Tests'));
        }
        $('.tier-results', this.$dom).removeClass('ajax-loading');
    };

    function MsgVisitor(suite, data) {
        this.$suite = suite;
        this.data = data;
        this.$results = $('.results', suite);
        this.msgSet = {};
        this.tiers = {};
        this.appTrans = null;
        this.versionChangeLinks = null;
        this.allCounts = {error: 0, warning: 0};
    }

    MsgVisitor.prototype.createTier = function(tierId, options) {
        var tier = new ResultsTier(this.$suite, tierId,
                                   this.tierOptions(options));
        return tier;
    };

    MsgVisitor.prototype.finish = function(msg) {
        var self = this;
        $('.result', this.$suite).each(function(i, res) {
            if (!$('.msg', res).length) {
                // No messages so no tier was created.
                self.getTier($('.tier-results', res).attr('data-tier'));
            }
        });
        $.each(this.tiers, function(tierId, tier) {
            var tierSum = tier.summarize();
            self.allCounts.error += tierSum.error;
            self.allCounts.warning += tierSum.warning;
        });
    };

    MsgVisitor.prototype.getMsgType = function(msg) {
         return msg['type'];
    };

    MsgVisitor.prototype.getTier = function(tierId, options) {
        if (typeof options === 'undefined')
            options = {app: null};
        if (!options.app
            && this.data.validation.ending_tier
            && this.data.validation.ending_tier < tierId) {
            options.testsWereRun = false;
        }
        if (typeof this.tiers[tierId] === 'undefined')
            this.tiers[tierId] = this.createTier(tierId, options);
        return this.tiers[tierId];
    };

    MsgVisitor.prototype.message = function(msg, options) {
        if (typeof this.msgSet[msg.uid] !== 'undefined')
            return;
        this.msgSet[msg.uid] = true;
        var tier = this.getTier(msg.tier, options),
            msgDiv = $('<div class="msg"><h5></h5></div>'),
            effectiveType = this.getMsgType(msg),
            prefix = effectiveType=='error' ? gettext('Error')
                                            : gettext('Warning');

        tier.tallyMsgType(effectiveType);
        msgDiv.attr('id', 'v-msg-' + msg.uid);
        msgDiv.addClass('msg-' + effectiveType);
        $('h5', msgDiv).html(msg.message);
        if (!msg.description) {
            msg.description = [];
        } else if (typeof(msg.description) === 'string') {
            // Currently it can be either of these:
            //      descripion: "foo"
            //      description: ["foo", "bar"]
            msg.description = [msg.description];
        }
        $.each(msg.description, function(i, val) {
            msgDiv.append(
                i == 0 ? format('<p>{0}: {1}</p>', [prefix, val]) :
                         format('<p>{0}</p>', [val])
            );
        });
        if (msg.description.length == 0) {
            msgDiv.append('<p>&nbsp;</p>');
        }
        if (msg.file) {
            msgDiv.append(this.messageContext(msg));
        }
        $('.tier-results', tier.$dom).append(msgDiv);
    };

    MsgVisitor.prototype.messageContext = function(msg) {
        var ctxFile = msg.file, ctxDiv, code, lines, innerCode;
        if (typeof(ctxFile) === 'string') {
            ctxFile = [ctxFile];
        }
        // e.g. ["silvermelxt_1.3.5.xpi", "chrome/silvermelxt.jar"]
        ctxFile = joinPaths(ctxFile);
        ctxDiv = $(format('<div class="context">' +
                          '<div class="file">{0}</div></div>', [ctxFile]));
        if (msg.context) {
            code = $('<div class="code"></div>');
            lines = $('<div class="lines"></div>');
            code.append(lines);
            innerCode = $('<div class="inner-code"></div>');
            code.append(innerCode);
            msg.context = formatCodeIndentation(msg.context);
            $.each(msg.context, function(n, c) {
                if (c == "") { return }
                // The line number refers to the middle element of the context,
                // not the first. Subtract one from the index to get the
                // right line number.
                lines.append($(format('<div>{0}</div>', [msg.line + n - 1])));
                innerCode.append($(format('<div>{0}</div>', [c])));
            });
            ctxDiv.append(code);
        }
        return ctxDiv;
    };

    MsgVisitor.prototype.tierOptions = function(options) {
        if (options && options.app) {
            options.app.trans = this.appTrans;
            options.app.versionChangeLinks = this.versionChangeLinks;
        }
        return options;
    };

    var CompatMsgVisitor = inherit(MsgVisitor, function(suite, data) {
        var self = this;
        this.appTrans = JSON.parse(this.$results.attr('data-app-trans'));
        this.versionChangeLinks = JSON.parse(this.$results.attr('data-version-change-links'));
        this.majorTargetVer = JSON.parse(this.$results.attr('data-target-version'));
        $.each(this.majorTargetVer, function(guid, version) {
            // 4.0b3 -> 4
            self.majorTargetVer[guid] = version.split('.')[0];
        });
    });

    CompatMsgVisitor.prototype.finish = function(msg) {
        MsgVisitor.prototype.finish.apply(this, arguments);
        // Since results are more dynamic on the compatibility page,
        // hide tiers without messages.
        $('.result', this.$suite).each(function(i, res) {
            if (!$('.msg', res).length)
                $(res).hide();
        });
        if (this.allCounts.error == 0 && this.allCounts.warning == 0) {
            $('#suite-results-tier-1').show();
            $('#suite-results-tier-1 h4').text(gettext('Compatibility Tests'));
        }
    };

    CompatMsgVisitor.prototype.getMsgType = function(msg) {
        return msg.compatibility_type ? msg.compatibility_type: msg['type'];
    };

    CompatMsgVisitor.prototype.message = function(msg) {
        var self = this, effectiveType = this.getMsgType(msg);
        if (msg.for_appversions) {
            eachAppVer(msg.for_appversions, function(guid, version, id) {
                var app = {guid: guid, version: version, id: id};
                if (version.split('.')[0] != self.majorTargetVer[guid])
                    // Since some errors span multiple versions, we only
                    // care about the first one specific to this target
                    return true;
                msg.tier = id;  // change the tier to match app/version
                MsgVisitor.prototype.message.apply(self, [msg, {app: app}]);
            });
        } else {
            if (effectiveType !== 'error')
                // For non-appversion messages, only show errors
                return;
            MsgVisitor.prototype.message.apply(this, arguments);
        }
    };

    CompatMsgVisitor.prototype.tierOptions = function(options) {
        options = MsgVisitor.prototype.tierOptions.apply(this, arguments);
        return options;
    };

    function buildResults(suite, data) {
        var vis,
            validation = data.validation,
            summaryTxt;

        if ($('.results', suite).hasClass('compatibility-results'))
            vis = new CompatMsgVisitor(suite, data);
        else
            vis = new MsgVisitor(suite, data);
        $.each(validation.messages, function(i, msg) {
            vis.message(msg);
        });
        vis.finish();

        if (validation.errors > 0) {
            summaryTxt = gettext('App failed validation.');
        } else {
            summaryTxt = gettext('App passed validation.');
        }
        $('.suite-summary span', suite).text(summaryTxt);
        $('.suite-summary', suite).show();
    }

    function eachAppVer(appVer, visit) {
        // Iterates an application/version map and calls
        // visit(gui, version, key) for each item.
        //
        // e.g. {'{ec8030f7-c20a-464f-9b0e-13a3a9e97384}':["4.0b1"]}
        // ->
        //      visit('{ec8030f7-c20a-464f-9b0e-13a3a9e97384}',
        //            "4.0b1",
        //            'ec8030f7-c20a-464f-9b0e-13a3a9e97384-40b1')
        if (appVer) {
            $.each(appVer, function(guid, all_versions) {
                $.each(all_versions, function(i, version) {
                    var key = (guid + '-' + version).replace(/[^a-z0-9_-]+/gi, '');
                    visit(guid, version, key);
                });
            });
        }
    }

    function resultSummary(numErrors, numWarnings, testsWereRun) {
        if (!testsWereRun) {
            return gettext('These tests were not run.');
        }
        // e.g. '1 error, 3 warnings'
        var errors = format(ngettext('{0} error', '{0} errors', numErrors),
                            [numErrors]),
            warnings = format(ngettext('{0} warning', '{0} warnings', numWarnings),
                              [numWarnings]);
        return format('{0}, {1}', errors, warnings);
    }

    function joinPaths(parts) {
        var p = '';
        $.each(parts, function(i, part) {
            if (!part || typeof(part) !== 'string') {
                // Might be null or empty string.
                return;
            }
            if (p.length) {
                p += '/';
                if (part.substring(0,1) === '/') {
                    // Prevent double slashes.
                    part = part.substring(1);
                }
            }
            p += part;
        });
        return p;
    }

    function formatCodeIndentation(lines) {
        var indent = null;
        $.each(lines, function(i, code) {
            if (code === null) {
                code = ''; // blank line
            }
            lines[i] = code;
            var m = code.length - code.replace(/^\s+/, '').length;
            if (indent === null) {
                indent = m;
            }
            // Look for the smallest common indent of white space.
            if (m < indent) {
                indent = m;
            }
        });
        $.each(lines, function(i, code) {
            if (indent > 0) {
                // Dedent all code to common level.
                code = code.substring(indent);
                lines[i] = code;
            }
            var n = code.search(/[^\s]/); // first non-space char
            if (n > 0) {
                lines[i] = '';
                // Add back the original indentation.
                for (var x=0; x<n; x++) {
                    lines[i] += '&nbsp;';
                }
                lines[i] += $.trim(code);
            }
        });
        return lines;
    }

    $('.addon-validator-suite', $doc).bind('validate', function(e) {
        var el = $(this),
            url = el.attr('data-validateurl');

        $('.test-tier,.tier-results', el).addClass('ajax-loading');

        $.ajax({type: 'POST',
                url: url,
                data: {},
                success: function(data) {
                    if (data.validation == '') {
                        // Note: traceback is in data.error
                        data.validation = {
                            ending_tier: 1,
                            messages: [{
                                'type':'error',
                                message: gettext('Error'),
                                description: [
                                    gettext('Validation task could not ' +
                                            'complete or completed with ' +
                                            'errors')],
                                tier: 1,
                                uid: '__global_error__'
                            }]
                        };
                    }
                    buildResults(el, data);
                    el.trigger('success.validation');
                },
                error: function(XMLHttpRequest, textStatus, errorThrown) {
                    buildResults(el, {
                        validation: {
                            ending_tier: 1,
                            messages: [{
                                'type':'error',
                                message: gettext('Error'),
                                description: [gettext('Internal server error')],
                                tier: 1,
                                uid: '__global_error__'
                            }]
                        }
                    });
                    el.trigger('badresponse.validation');
                },
                dataType: 'json'
        });
    });

    // Validate when the page loads.
    $('#addon-validator-suite').trigger('validate');

};
