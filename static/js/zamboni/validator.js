import $ from 'jquery';
import { sortBy } from 'underscore';
import { format } from '../lib/format';

$(document).ready(function () {
  if ($('.addon-validator-suite').length) {
    initValidator();
  }
});

function initValidator($doc) {
  $doc = $doc || $(document);

  function inherit(OtherClass, constructor) {
    let NewClass = function () {
      OtherClass.apply(this, arguments);
      if (typeof constructor !== 'undefined') {
        constructor.apply(this, arguments);
      }
    };
    $.extend(NewClass.prototype, OtherClass.prototype);
    return NewClass;
  }

  function emptyFn() {
    return null;
  }

  function ResultsTier($suite, tierId, options) {
    if (typeof options === 'undefined') {
      options = {};
    }
    if (typeof options.app === 'undefined') {
      options.app = null;
    }
    if (typeof options.testsWereRun === 'undefined') {
      options.testsWereRun = true;
    }
    this.$results = $('.results', $suite);
    this.app = options.app;
    this.testsWereRun = options.testsWereRun;
    this.counts = { error: 0, warning: 0, notice: 0 };
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

  ResultsTier.prototype.clear = function () {
    this.$tierResults.empty();
  };

  ResultsTier.prototype.tallyMsgType = function (type_) {
    this.counts[type_] += 1;
  };

  ResultsTier.prototype.createDom = function () {
    let $tier = $($('.template', this.$suite).html().trim());
    $tier.attr('id', 'suite-results-tier-' + this.tierId);
    return $tier;
  };

  ResultsTier.prototype.summarize = function () {
    let sm = resultSummary(
        this.counts.error,
        this.counts.warning,
        this.counts.notice,
        this.testsWereRun,
      ),
      resultClass,
      summaryMsg;
    $('.result-summary', this.$dom)
      .css('visibility', 'visible')
      .empty()
      .text(sm);
    if (this.counts.error) {
      resultClass = 'tests-failed';
    } else if (this.counts.warning) {
      resultClass = 'tests-passed-warnings';
    } else if (this.counts.notice) {
      resultClass = 'tests-passed-notices';
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
    this.$tierResults
      .removeClass(
        'ajax-loading tests-failed ' +
          'tests-passed tests-passed-warnings ' +
          'tests-passed-notices tests-notrun',
      )
      .addClass(resultClass);
    if ($('.test-tier', this.$suite).length) {
      this.topSummary();
    }
    return this.counts;
  };

  ResultsTier.prototype.topSummary = function () {
    let $top = $(
        '[class~="test-tier"]' + '[data-tier="' + this.tierId + '"]',
        this.$suite,
      ),
      summaryMsg = resultSummary(
        this.counts.error,
        this.counts.warning,
        this.counts.notice,
        this.testsWereRun,
      );

    $('.tier-summary', $top).text(summaryMsg);
    $top.removeClass(
      'ajax-loading',
      'tests-failed',
      'tests-passed',
      'tests-notrun',
    );
    if (this.counts.error > 0) {
      $top.addClass('tests-failed');
    } else if (this.counts.warning > 0) {
      $top.addClass('tests-warnings');
    } else if (this.testsWereRun) {
      $top.addClass('tests-passed');
    } else {
      $top.addClass('tests-notrun');
    }
  };

  ResultsTier.prototype.wakeUp = function () {
    let $title = $('h4', this.$dom),
      changeLink;
    $('.tier-results', this.$dom).empty();
    this.$dom.removeClass('hidden');
    this.$dom.show();
    if (this.app) {
      // Override the title with a special app/version title
      $title.text(
        format(
          '{0} {1} {2}',
          this.app.trans[this.app.guid],
          this.app.version,
          gettext('Tests'),
        ),
      );
      changeLink =
        this.app.versionChangeLinks[this.app.guid + ' ' + this.app.version];
      if (changeLink) {
        this.$dom.prepend(
          format(
            '<a class="version-change-link" href="{0}">{1}</a>',
            changeLink,
            // L10n: Example: Changes in Firefox 5
            gettext(
              format(
                'Changes in {0} {1}',
                this.app.trans[this.app.guid],
                /\d+/.exec(this.app.version),
              ),
            ),
          ),
        );
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
    this.allCounts = { error: 0, warning: 0 };
    this.fileURL = suite.data('fileUrl');
    this.fileID = suite.data('fileId');
  }

  MsgVisitor.prototype.createTier = function (tierId, options) {
    let tier = new ResultsTier(this.$suite, tierId, this.tierOptions(options));
    return tier;
  };

  MsgVisitor.prototype.finish = function () {
    let self = this;
    $('.result', this.$suite).each(function (i, res) {
      if (!$('.msg', res).length) {
        // No messages so no tier was created.
        self.getTier($('.tier-results', res).attr('data-tier'));
      }
    });
    $.each(this.tiers, function (tierId, tier) {
      let tierSum = tier.summarize();
      self.allCounts.error += tierSum.error;
      self.allCounts.warning += tierSum.warning;
    });
  };

  MsgVisitor.prototype.clear = function () {
    $.each(this.tiers, function (tierId, tier) {
      tier.clear();
    });
  };

  MsgVisitor.prototype.getMsgType = function (msg) {
    return msg['type'];
  };

  MsgVisitor.prototype.getTier = function (tierId, options) {
    if (typeof options === 'undefined') {
      options = { app: null };
    }
    if (
      !options.app &&
      this.data.validation.ending_tier &&
      this.data.validation.ending_tier < tierId
    ) {
      options.testsWereRun = false;
    }
    if (typeof this.tiers[tierId] === 'undefined') {
      this.tiers[tierId] = this.createTier(tierId, options);
    }
    return this.tiers[tierId];
  };

  MsgVisitor.prototype.filterMessage = function (msg) {
    return !(this.hideIgnored && msg.ignored);
  };

  MsgVisitor.prototype.message = function (msg, options) {
    if (!this.filterMessage(msg)) {
      return;
    }

    if (typeof this.msgSet[msg.uid] !== 'undefined') {
      return;
    }
    this.msgSet[msg.uid] = true;

    let tier = this.getTier(msg.tier, options),
      msgDiv = $('<div class="msg"><h5></h5></div>'),
      effectiveType = this.getMsgType(msg),
      prefix = effectiveType == 'error' ? gettext('Error') : gettext('Warning');

    tier.tallyMsgType(effectiveType);
    msgDiv.attr('id', 'v-msg-' + msg.uid);
    msgDiv.addClass('msg-' + effectiveType);

    // The "message" and "description" properties are escaped and linkified
    // before we receive them.
    $('h5', msgDiv).html(msg.message); // Sanitized HTML value.

    // The validator returns the "description" as either string, or
    // arrays of strings. We turn it into arrays when sanitizing.
    $.each(msg.description, function (i, val) {
      let $desc = $('<p>').html(val); // Sanitized HTML value.
      if (i === 0) {
        $desc.prepend(format('<strong>{0}:</strong> ', prefix));
      }
      msgDiv.append($desc);
    });

    if (msg.file) {
      let file = msg.file;
      if (typeof file !== 'string') {
        // For sub-packages, this will be a list of archive paths and
        // a final file path, which we need to turn into a string.
        //   ['foo.xpi', 'chrome/thing.jar', 'content/file.js']
        file = file.join('/');
      }
      let $link;

      if (this.fileURL && this.fileID) {
        let url = this.fileURL + '?path=' + file;
        if (msg.line) {
          url += '#L' + msg.line;
        }
        $link = $('<a>', {
          href: url,
          text: file,
          target: 'file-viewer-' + this.fileID,
        });
      } else {
        // There's no file browse URL for bare file uploads, so
        // just display a path without a link to the sources.
        $link = $('<span>', { text: file });
      }

      let $context = $('<div class="context">').append(
        $('<div class="file">').append($link),
      );

      if (msg.context) {
        let $code = $('<div class="code"></div>');
        let $lines = $('<div class="lines"></div>');
        let $innerCode = $('<div class="inner-code"></div>');

        $code.append($lines, $innerCode);

        // The line number in the message refers to the middle
        // line of the context, so adjust accordingly.
        let offset = Math.floor(msg.context.length / 2);
        msg.context = formatCodeIndentation(msg.context);
        $.each(msg.context, function (idx, code) {
          if (code != null) {
            $lines.append($('<div>', { text: msg.line + idx - offset }));
            $innerCode.append($('<div>', { text: code }));
          }
        });
        $context.append($code);
      } else if (msg.line && typeof msg.column !== 'undefined') {
        // Normally, the line number would be displayed with the
        // context. If we have no context, display it with the
        // filename.
        $link.text(
          format(gettext('{0} line {1} column {2}'), [
            file,
            msg.line,
            msg.column,
          ]),
        );
      } else if (msg.line) {
        $link.text(format(gettext('{0} line {1}'), [file, msg.line]));
      }

      msgDiv.append($context);
    }

    $('.tier-results', tier.$dom).append(msgDiv);
  };

  MsgVisitor.prototype.tierOptions = function (options) {
    if (options && options.app) {
      options.app.trans = this.appTrans;
      options.app.versionChangeLinks = this.versionChangeLinks;
    }
    return options;
  };

  function buildResults(suite, data) {
    let vis,
      validation = data.validation,
      summaryTxt;

    function sortByType(messages) {
      let ordering = ['error', 'warning', 'notice', undefined /* no type */];
      return sortBy(messages, function (msg) {
        return ordering.indexOf(msg.type);
      });
    }

    function rebuildResults() {
      vis = new MsgVisitor(suite, data);
      $.each(sortByType(validation.messages), function (i, msg) {
        vis.message(msg);
      });
      vis.finish();

      if (validation.errors > 0) {
        summaryTxt = gettext('Add-on failed validation.');
      } else {
        summaryTxt = gettext('Add-on passed validation.');
      }
      $('.suite-summary span', suite).text(summaryTxt);
      $('.suite-summary', suite).show();
    }
    rebuildResults();
  }

  function resultSummary(numErrors, numWarnings, numNotices, testsWereRun) {
    if (!testsWereRun) {
      return gettext('These tests were not run.');
    }
    // e.g. '1 error, 3 warnings'
    let errors = format(ngettext('{0} error', '{0} errors', numErrors), [
        numErrors,
      ]),
      warnings = format(ngettext('{0} warning', '{0} warnings', numWarnings), [
        numWarnings,
      ]),
      notices = format(ngettext('{0} notice', '{0} notices', numNotices), [
        numNotices,
      ]);
    return format('{0}, {1}, {2}', errors, warnings, notices);
  }

  function formatCodeIndentation(lines) {
    // Replaces leading tabs with spaces, and then trims the
    // smallest common indentation space from each line.

    function retab(line, tabstops) {
      // Replaces tabs with spaces, to match the given tab stops.

      let SPACES = '                                ';
      tabstops = Math.min(tabstops || 4, SPACES.length);

      function replace_tab(full_match, non_tab) {
        if (non_tab) {
          position += non_tab.length;
          return non_tab;
        } else {
          let pos = position;
          position += position % tabstops || tabstops;
          return SPACES.substr(0, position - pos);
        }
      }

      let position = 0;
      return line.replace(/([^\t]+)|\t/g, replace_tab);
    }

    // Retab all lines and find the common indent.
    let indent = Infinity;
    lines = lines.map(function (line) {
      // When the context line is at the start or end of the file,
      // the line before or after the context line will be null.
      if (line == null) {
        return null;
      }

      // We need the replace function to run even if there's no
      // whitespace, so `indent` is properly updated. Stick with
      // \s* rather than \s+.
      return line.replace(/^(\s*)/, function (match) {
        match = retab(match);
        indent = Math.min(indent, match.length);
        return match;
      });
    });

    // Trim off the common white space.
    return lines.map(function (line) {
      // Line may be null. Do not try to slice null.
      return line && line.slice(indent);
    });
  }

  $('.addon-validator-suite', $doc).on('validate', function (e) {
    let el = $(this),
      data = el.data();

    if (data.annotateUrl) {
      el.on('change', '.ignore-duplicates-checkbox', function (event) {
        let $target = $(event.target);
        $.ajax({
          type: 'POST',
          url: data.annotateUrl,
          data: {
            message: $target.attr('name'),
            ignore_duplicates: $target.prop('checked') || undefined,
          },
          dataType: 'json',
        });
      });
    }

    if (data.validation) {
      buildResults(el, { validation: data.validation });
      return;
    }

    $('.test-tier,.tier-results', el).addClass('ajax-loading');

    $.ajax({
      type: 'POST',
      url: data.validateurl,
      data: {},
      success: function (data) {
        if (data.validation == '') {
          // Note: traceback is in data.error
          data.validation = {
            ending_tier: 1,
            messages: [
              {
                type: 'error',
                message: gettext('Error'),
                description: [
                  gettext(
                    'Validation task could not ' +
                      'complete or completed with ' +
                      'errors',
                  ),
                ],
                tier: 1,
                uid: '__global_error__',
              },
            ],
          };
        }
        buildResults(el, data);
        el.trigger('success.validation');
      },
      error: function (XMLHttpRequest, textStatus, errorThrown) {
        buildResults(el, {
          validation: {
            ending_tier: 1,
            messages: [
              {
                type: 'error',
                message: gettext('Error'),
                description: [gettext('Internal server error')],
                tier: 1,
                uid: '__global_error__',
              },
            ],
          },
        });
        el.trigger('badresponse.validation');
      },
      dataType: 'json',
    });
  });

  // Validate when the page loads.
  $('#addon-validator-suite').trigger('validate');
}
