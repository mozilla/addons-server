"use strict";

if (typeof diff_match_patch !== 'undefined') {
    diff_match_patch.prototype.diff_prettyHtml = function(diffs) {
        /* An override of prettyHthml from diff_match_patch. This
           one will not put any style attrs in the ins or del. */
        var html = [];
        for (var x = 0; x < diffs.length; x++) {
            var op = diffs[x][0];    // Operation (insert, delete, equal)
            var data = diffs[x][1];  // Text of change.
            var lines = data.split('\n');
            for (var t = 0; t < lines.length; t++) {
                /* A diff gets an empty element on the end (the last \n).
                   Unless the diff line in question does not have a new line on
                   the end. We can't just set lines.length - 1, because this
                   will just chop off lines. But if we don't trim these empty
                   lines we'll end up with lines between each diff. */
                if ((t + 1) == lines.length && lines[t] == '') {
                    continue;
                }
                switch (op) {
                    /* The syntax highlighter needs an extra space
                       to do it's work. */
                    case DIFF_INSERT:
                        html.push('+' + lines[t] + '\n');
                        break;
                    case DIFF_DELETE:
                        html.push('-' + lines[t] + '\n');
                        break;
                    case DIFF_EQUAL:
                        html.push(' ' + lines[t] + '\n');
                        break;
                }
            }
        }
        return html.join('');
    };
}

var config = {
    diff_context: 2,
    needreview_pattern: /\.(js|jsm|xul|xml|x?html?|manifest|sh|py)$/i
};

if (typeof SyntaxHighlighter !== 'undefined') {
    /* Turn off double click on the syntax highlighter. */
    SyntaxHighlighter.defaults['quick-code'] = false;
    SyntaxHighlighter.defaults['auto-links'] = false;
    SyntaxHighlighter.amo_vars = {'left_line': 0, 'right_line': 0, 'is_diff': false};

    SyntaxHighlighter.Highlighter.prototype.getLineNumbersHtml = function(code, lineNumbers) {
        return '';
    };

    SyntaxHighlighter.Highlighter.prototype.getLineHtml = function(lineIndex, lineNumber, code) {
        var classes = [
            'original',
            'line',
            'number' + lineNumber,
            'index' + lineIndex,
        ];
        var td_classes = [
            'td-line-code',
            'alt' + (lineNumber % 2 + 1)
        ];
        var line_classes = classes.slice();
        var line_attrs = [];

        classes.push('line-code');
        line_classes.push('line-number');

        if (this.isLineHighlighted(lineNumber)) {
            classes.push('highlighted');
        }

        if (lineNumber === 0) {
            classes.push('break');
        }

        /* For diffs we have to do more work to make the line numbers
         * do what we'd like. */
        var vars = SyntaxHighlighter.amo_vars;
        var line_id = 'L' + lineNumber;
        if (vars.is_diff) {
            // Wow. This is terrible.
            if (code.match(/<code class=".*?comments.*?">/)) {
                // Line deletion.
                vars.right_line += 1;
                line_id = 'D' + vars.right_line;

                td_classes.push('delete');
                line_classes.push('delete');
            } else {
                var lines = vars.highlighted_lines || [];

                vars.left_line += 1;
                line_id = 'L' + vars.left_line;

                var new_line;
                if (vars.left_line in lines) {
                    new_line = lines[vars.left_line];
                }

                line_attrs.push('data-linenumber="' + vars.left_line + '"')

                if (code.match(/<code class=".*?string.*?">/)) {
                    // Line addition.
                    td_classes.push('add');
                    line_classes.push('add');
                    if (new_line) {
                        code = '<code class="xml plain">+</code>' + new_line;
                    }
                } else {
                    // Common line.
                    vars.right_line += 1;
                    if (new_line) {
                        code = '<code class="xml plain">\u00a0</code>' + new_line;  // Non-breaking space.
                    }
                }
            }
        } else {
            line_attrs.push('data-linenumber="' + lineNumber + '"');
            if (vars.lines) {
                vars.lines[lineNumber] = code;
            }
        }

        line_attrs.push('id="' + line_id + '"',
                        'href="#' + line_id + '"',
                        'class="' + line_classes.join(' ') + '"');

        return '<tr class="tr-line">' +
                    '<td class="td-line-number"><a ' + line_attrs.join(' ') + '></a></td>' +
                    '<td class="' + td_classes.join(' ') + '"><span class="' + classes.join(' ') + '">' + code + '</span></td>' +
               '</tr>';
    };

    SyntaxHighlighter.Highlighter.prototype.getHtml = function(code) {
        // Copied from shCore.js with slight modifications, to output
        // code and line numbers as a table, rather than parallel divs.
        //
        // Original:
        //   https://github.com/mozilla/olympia/blob/a35ab083/static/js/lib/syntaxhighlighter/shCore.js#L1552
        var html = '',
            classes = [ 'syntaxhighlighter' ],
            tabSize,
            matches,
            lineNumbers;

        // process light mode
        if (this.getParam('light') == true)
            this.params.toolbar = this.params.gutter = false;

        if (this.getParam('collapse') == true)
            classes.push('collapsed');

        classes.push('nogutter');

        // add custom user style name
        classes.push(this.getParam('class-name'));

        // add brush alias to the class name for custom CSS
        classes.push(this.getParam('brush'));

        lineNumbers = this.figureOutLineNumbers(code);

        // find matches in the code using brushes regex list
        matches = this.findMatches(this.regexList, code);
        // processes found matches into the html
        html = this.getMatchesHtml(code, matches);
        // finally, split all lines so that they wrap well
        html = this.getCodeLinesHtml(html, lineNumbers);

        // finally, process the links
        if (this.getParam('auto-links'))
            html = processUrls(html);

        if (typeof(navigator) != 'undefined' && navigator.userAgent && navigator.userAgent.match(/MSIE/))
            classes.push('ie');

        var line_order = Math.ceil(Math.log(lineNumbers.length) / Math.log(10)) + 1;
        var lines_width = 1.2 * line_order + 4;  // 1.2 ex width per digit, just to be safe, + 4 for padding.

        if (SyntaxHighlighter.amo_vars.lines) {
            // Just generating HTML for the diff highlighter.
            // Bail early.
            return '';
        }

        html =
            '<div id="highlighter_' + this.id + '" class="' + classes.join(' ') + '">'
                + (this.getParam('toolbar') ? sh.toolbar.getHtml(this) : '')
                    + '<table border="0" cellpadding="0" cellspacing="0">'
                        + this.getTitleHtml(this.getParam('title'))
                            + '<colgroup><col class="highlighter-column-line-numbers" style="width: ' + lines_width + 'ex;"/>'
                                      + '<col class="highlighter-column-code"/></colgroup>'
                            + '<tbody>'
                                + html
                            + '</tbody>'
                    + '</table>'
            + '</div>';

        return html;
    };
}

jQuery.fn.numberInput = function(increment) {
    this.each(function() {
        var $self = $(this);
        $self.addClass("number-combo-input");

        var height = $self.outerHeight(false) / 2;

        var $dom = $('<span>', { 'class': 'number-combo' })
                     .append($('<a>', { 'class': 'number-combo-button-down',
                                        'href': '#', 'text': '↓' }))
                     .append($('<a>', { 'class': 'number-combo-button-up',
                                        'href': '#', 'text': '↑' }));

        var $up = $dom.find('.number-combo-button-up').click(_pd(function(event, count) {
            count = count || (event.ctrlKey ? increment : 1) || 1;
            $self.val(Number($self.val()) + count);
            $self.change();
        }));
        var $down = $dom.find('.number-combo-button-down').click(_pd(function(event, count) {
            count = count || (event.ctrlKey ? increment : 1) || 1;
            $self.val(Math.max(Number($self.val()) - count, 0));
            $self.change();
        }));

        $.each(['change', 'keypress', 'input'], function(i, event) {
            $self.bind(event, function() {
                $self.val($self.val().replace(/\D+/, ''));
            });
        });
        $self.keypress(function(event) {
            if (event.keyCode == KeyEvent.DOM_VK_UP) {
                $up.click();
            } else if (event.keyCode == KeyEvent.DOM_VK_DOWN) {
                $down.click();
            } else if (event.keyCode == KeyEvent.DOM_VK_PAGE_UP) {
                $up.trigger('click', increment);
            } else if (event.keyCode == KeyEvent.DOM_VK_PAGE_DOWN) {
                $down.trigger('click', increment);
            }
        });

        $self.after($dom);
        $dom.prepend(this);
    });
    return this;
};

jQuery.fn.appendMessage = function(message) {
    $(this).each(function() {
        var $self = $(this),
            $container = $self.find('.message-inner');

        if (!$container.length) {
            $container = $('<div>', { 'class': 'message-inner' });
            $self.append($('<div>', { 'class': 'message' }).append($container))
                 .addClass('message-container');
        }

        $container.append($('<div>')[typeof message == "string" ? 'text' : 'html'](message));
    });
    return this;
};

function bind_viewer(nodes) {
    $.each(nodes, function(x) {
        nodes['$'+x] = $(nodes[x]);
    });
    function Viewer() {
        var self = this;
        this.nodes = nodes;
        this.wrapped = true;
        this.hidden = false;
        this.top = null;
        this.last = null;
        this.compute = function(node) {
            var $diff = node.find('#diff'),
                $content = node.find('#content');

            if ($diff.length) {
                var dmp = new diff_match_patch();

                // Line diffs http://code.google.com/p/google-diff-match-patch/wiki/LineOrWordDiffs
                var a = dmp.diff_linesToChars_($diff.siblings('.right').text(),
                                               $diff.siblings('.left').text());
                var diffs = dmp.diff_main(a[0], a[1], false);

                dmp.diff_charsToLines_(diffs, a[2]);

                $diff.text(dmp.diff_prettyHtml(diffs)).show();

                var highlighted_lines = []
                SyntaxHighlighter.amo_vars = {'left_line': 0, 'right_line': 0, 'is_diff': false,
                                              'lines': highlighted_lines};


                var $left = $diff.siblings('.left');
                $('<div>').hide().append($left).insertAfter($diff);
                SyntaxHighlighter.highlight({}, $left[0]);

                /* Reset the syntax highlighter variables. */
                SyntaxHighlighter.amo_vars = {'left_line': 0, 'right_line': 0, 'is_diff': true,
                                              'highlighted_lines': highlighted_lines};
                SyntaxHighlighter.highlight({}, $diff[0]);
                // Note SyntaxHighlighter has nuked the node and replaced it.
                $diff = node.find('#diff');
            } else if ($content) {
                SyntaxHighlighter.highlight({}, $content[0]);
                // Note SyntaxHighlighter has nuked the node and replaced it.
            }


            this.compute_messages(node);

            if (window.location.hash && window.location.hash != 'top') {
                window.location = window.location;
            }

            this.show_selected();
        };
        this.update_message_filters = function() {
            if (file_metadata.automatedSigning) {
                this.hideNonSigning = $('#signing-hide-unnecessary').prop('checked');

                // Hiding ignored messages only makes sense if we're only
                // showing signing-related messages.
                $('#signing-hide-ignored-container input').prop('disabled', !this.hideNonSigning);
                if (!this.hideNonSigning) {
                    $('#signing-hide-ignored').prop('checked', false);
                }

                this.hideIgnored = $('#signing-hide-ignored').prop('checked');
            }

            var $root = this.nodes.$root;
            $root.addClass('messages-signing');
            $root.toggleClass('messages-duplicate', !this.hideIgnored);
            $root.toggleClass('messages-all', !this.hideNonSigning);

            $("#signing-hide-ignored-container").toggle(!!this.validation.signing_ignored_summary);
        };
        this.message_type_map = {
            'error': 'error',
            'warning': 'warning',
            'notice': 'info'
        };
        this.message_classes = function(message, base_class) {
            base_class = base_class || '';
            var classes = [''];
            if (message.signing_severity || message.type == "error") {
                // For the moment, we only ignore messages in signing
                // validation.
                if (message.ignored) {
                    classes.push('-ignored');
                } else {
                    classes.push('-signing');
                }
            }
            return classes.map(function(cls) { return [base_class, message.type, cls].join(""); });
        };
        this.compute_messages = function(node) {
            var $diff = node.find('#diff'),
                path = this.nodes.$files.find('a.file.selected').attr('data-short'),
                messages = [],
                self = this;

            if (this.messages) {
                if (this.messages.hasOwnProperty(''))
                    messages = messages.concat(this.messages['']);
                if (this.messages.hasOwnProperty(path))
                    messages = messages.concat(this.messages[path]);
            }

            _.each(messages, function(message) {
                var $line = $('#L' + message.line),
                    title = $line.attr('title'),
                    html = ['<div>',
                            format('<strong>{0}{1}: {2}</strong>',
                                   message.type[0].toUpperCase(),
                                   message.type.substr(1),
                                   message.message)];

                if (message.ignore_duplicates != null && file_metadata.annotateUrl) {
                    var checked = message.ignore_duplicates ? 'checked="checked" ' : '';

                    html.push('<p><label>',
                              format('<input type="checkbox" class="ignore-duplicates-checkbox"' +
                                     ' {0}name="{1}">', [checked, _.escape(JSON.stringify(message))]),
                              ' ', gettext('Ignore this message in future updates'), '</label></p>');
                }

                if (message.signing_severity && file_metadata.automatedSigning) {
                    html.push(format(
                        '<p><label>{0}</label> {1}</p>',
                        [gettext('Severity for automated signing:'),
                         message.signing_severity]));
                }

                $.each(message.description, function(i, msg) {
                    html.push('<p>', msg, '</p>');
                });

                html.push('</div>');
                var message_class = this.message_classes(message, 'message-').join(' ');
                var $dom = $(html.join(''));

                if (message.line != null && $line.length) {
                    $line.addClass(this.message_classes(message).join(' '))
                         .parent().addClass(message_class)
                         .appendMessage($dom.addClass(message_class));
                } else {
                    $('#diff-wrapper').before(
                        $('<div>', { 'class': 'notification-box' })
                            .addClass(this.message_type_map[message.type])
                            .addClass(message_class)
                            .append($dom));
                }
            }, this);

            if ($diff.length || messages) {
                /* Build out the diff bar based on the line numbers. */
                var $sb = $('.diff-bar'),
                    $gutter = $('.syntaxhighlighter tbody'),
                    $lines = $gutter.find('.line-number');

                $sb.empty();

                if ($lines.length) {
                    /* Be sure to make all size calculations before modifying
                     * the DOM so that we don't force unnecessary reflows. */
                    var changes = [];
                    var flush = function($line, bottom) {
                        var top = ($start.offset().top - gutter_top) * 100 / gutter_height;
                        var height = (bottom - $start.offset().top) * 100 / gutter_height,
                            style = { 'height': Math.min(height, 100) + '%',
                                      'top': top + '%'};

                        if ($prev && !$prev.attr('class')) {
                            style['border-top-width'] = '1px';
                            style['margin-top'] = '-1px';
                        }
                        if ($line && !$line.attr('class')) {
                            style['border-bottom-width'] = '1px';
                            style['margin-bottom'] = '-1px';
                        }

                        changes.push([$start, style]);

                        $prev = $start;
                        $start = $line;
                    };

                    var gutter_top = $gutter.offset().top;
                    var gutter_height = $gutter.height();
                    var $prev, $start = null;
                    $lines.each(function() {
                        var $line = $(this);
                        if (!$start) {
                            $start = $line;
                        } else if ($line.attr('class') != $start.attr('class')) {
                            flush($line, $line.offset().top);
                        }
                    });
                    flush(null, gutter_top + gutter_height);

                    $.each(changes, function(i, change) {
                        var $start = change[0], style = change[1];

                        var $link = $('<a>', { 'href': $start.attr('href'), 'class': $start.attr('class'),
                                               'css': style }).appendTo($sb);

                        if ($start.is('.error, .notice, .warning')) {
                            $link.appendMessage($start.parent().find('.message-inner > div').clone());
                        }
                    });

                    this.$diffbar = $sb;
                    this.$viewport = $('<div>', { 'class': 'diff-bar-viewport' });
                    this.$gutter = $gutter;
                    $sb.append(this.$viewport);

                    $diff.addClass('diff-bar-height');
                    $sb.removeClass('js-hidden');

                    this.update_viewport(true);
                }
            }
        };
        this.update_validation = function(data, skip_compute) {
            var viewer = this;

            $('#validating').hide();
            if (data.validation) {
                this.validation = data.validation;
                this.update_message_filters();

                this.messages = {};
                _.each(data.validation.messages, function(message) {
                    // Skip warnings for known libraries.
                    if (message.id.join('/') == 'testcases_content/test_packed_packages/blacklisted_js_library')
                        return;

                    var path = [].concat(message.file).join("/");

                    if (!this.messages[path]) {
                        this.messages[path] = [];
                    }
                    this.messages[path].push(message);
                }, this);

                this.known_files = {};
                var metadata = data.validation.metadata;
                if (metadata) {
                    if (metadata.jetpack_sdk_version) {
                        $('#jetpack-version').show()
                            .find('span').text(metadata.jetpack_sdk_version);
                    }

                    var identified_files = {};
                    (function process_files(prefix, metadata) {
                        if (metadata.identified_files) {
                            var files = metadata.identified_files;
                            for (var path in files) {
                                var file = files[path];
                                path = prefix + path;
                                viewer.known_files[path] = file;
                            }
                        }

                        if (metadata.sub_packages) {
                            for (var prefix in metadata.sub_packages) {
                                process_files(prefix, metadata.sub_packages[prefix]);
                            }
                        }
                    })('', metadata);
                }

                this.nodes.$files.find('.file').each(function() {
                    var $self = $(this);

                    var known = viewer.known_files[$self.attr('data-short')];
                    if (known) {
                        var msg = ['Identified:'];
                        if ('library' in known) {
                            msg.push(
                                format('    Library: {library} {version}\n',
                                       known));
                        }
                        msg.push(format('    Original path: {0}', known.path));

                        $self.attr('title', msg.join('\n'))
                             .addClass('known')
                             .addClass('tooltip');
                    }

                    var messages = self.messages[$self.attr('data-short')];
                    if (messages) {
                        var classes = _.uniq(_.flatten(messages.map(function(msg) {
                            return viewer.message_classes(msg);
                        })));

                        $self.addClass(classes.join(' '));
                    }
                });

                this.nodes.$files.find('.directory').each(function() {
                    var $self = $(this);
                    var $ul = $self.parent().next();

                    $.each(['warning', 'error', 'notice'], function(i, type) {
                        if ($ul.find('.' + type + ':eq(0)').length) {
                            $self.addClass(type);
                        }
                    });
                    if (!$ul.find('.file:not(.known):eq(0)').length) {
                        $self.addClass('known');
                    }
                });

                if (!skip_compute) {
                    this.compute_messages($('#content-wrapper'));
                }
            }

            if (data.error) {
                $('#validating').after(
                    $('<div>', { 'class': 'notification-box error',
                                 'text': format('{0} {1}', file_metadata.validationFailed,
                                                data.error) }));
            }
        };
        this.fix_vertically = function($node, changes, resize) {
            var rect = $node.parent()[0].getBoundingClientRect(),
                window_height = $(window).height();
            if (resize) {
                changes.push([$node, { 'height': Math.min(rect.bottom - rect.top,
                                                 window_height) + 'px' }]);
            }

            if (rect.bottom <= window_height) {
                changes.push([$node, { 'position': 'absolute', 'top': '', 'bottom': '0' }]);
            } else if (rect.top > 0) {
                changes.push([$node, { 'position': 'absolute', 'top': '0', 'bottom': '' }]);
            } else {
                changes.push([$node, { 'position': 'fixed', 'top': '0px', 'bottom': '' }]);
            }
        };
        this.update_viewport = function(resize) {
            /* Be sure to make all size calculations before modifying
             * the DOM so that we don't force unnecessary reflows. */

            var $viewport = this.$viewport,
                changes = [];

            if (resize) {
                var height = $('#controls-inner').height() / $('#metadata').width();
                changes.push([$('#files-inner'), { 'padding-bottom': height + 'em' }]);
            }

            this.fix_vertically(this.nodes.$files, changes, resize);

            if ($viewport) {
                var $gutter = this.$gutter,
                    $diffbar = this.$diffbar,
                    gr = $gutter[0].getBoundingClientRect(),
                    gh = gr.bottom - gr.top,
                    height = Math.max(0, Math.min(gr.bottom, $(window).height())
                                       - Math.max(gr.top, 0));

                changes.push([$viewport,
                              { 'height': Math.min(height / gh * 100, 100) + '%',
                                'top': -Math.min(0, gr.top) / gh * 100 + '%' }]);

                this.fix_vertically($diffbar, changes, resize);
            }

            $.each(changes, function (i, change) {
                change[0].css(change[1]);
            });

            if (resize) {
                /* Opera does not handle max-height:100% properly in
                 * this case, and I won't place any bets on IE. */
                var $wrapper = $('#files-wrapper');
                $wrapper.css({ 'max-height': $wrapper.parent().height() + 'px' });
            }
        };
        this.toggle_leaf = function($leaf) {
            if ($leaf.hasClass('open')) {
                this.hide_leaf($leaf);
            } else {
                this.show_leaf($leaf);
            }
        };
        this.hide_leaf = function($leaf) {
            $leaf.removeClass('open').addClass('closed')
                 .closest('li').next('ul').hide();
        };
        this.show_leaf = function($leaf) {
            /* Exposes the leaves for a given set of node. */
            $leaf.removeClass('closed').addClass('open')
                 .closest('li').next('ul').show();
        };
        this.selected = function($link) {
            /* Exposes all the leaves to an element */
            $link.parentsUntil('ul.root').filter('ul').show()
                 .each(function() {
                        $(this).prev('li').find('a:first')
                               .removeClass('closed').addClass('open');
            });
            if ($('.breadcrumbs li').length > 2) {
                $('.breadcrumbs li').eq(2).text($link.attr('data-short'));
            } else {
                $('.breadcrumbs').append(format('<li>{0}</li>', $link.attr('data-short')));
            }

            this.show_selected();
        };
        this.show_selected = function() {
            var $sel = this.nodes.$files.find('.selected'),
                $cont = $('#files-wrapper');

            if ($sel.position().top < 0) {
                $cont.scrollTop($cont.scrollTop() + $sel.position().top);
            } else {
                /* Unfortunately, jQuery does not provide anything
                   comparable to clientHeight, which we can't do without */
                var offset = $sel.position().top + $sel.outerHeight(false) - $cont[0].clientHeight;
                if (offset > 0) {
                    $cont.scrollTop($cont.scrollTop() + offset);
                }
            }
        };
        this.load = function($link) {
            /* Accepts a jQuery wrapped node, which is part of the tree.
               Hides content, shows spinner, gets the content and then
               shows it all. */
            var self = this,
                $old_wrapper = $('#content-wrapper');
            $old_wrapper.hide();
            this.nodes.$thinking.show();
            this.update_viewport(true);
            if (location.hash != 'top') {
                if (history.pushState !== undefined) {
                    this.last = $link.attr('href');
                    history.pushState({ path: $link.text() }, '', $link.attr('href') + '#top');
                }
            }
            $old_wrapper.load($link.attr('href').replace('/file/', '/fragment/') + ' #content-wrapper',
                function(response, status, xhr) {
                    self.nodes.$thinking.hide();
                    /* Cope with an error a little more nicely. */
                    if (status != 'error') {
                        $(this).children().unwrap();
                        var $new_wrapper = $('#content-wrapper');
                        self.compute($new_wrapper);
                        $new_wrapper.slideDown();
                    }
                }
            );
        };
        this.select = function($link) {
            /* Given a node, alters the tree and then loads the content. */
            this.nodes.$files.find('a.selected').each(function() {
                $(this).removeClass('selected');
            });
            $link.addClass('selected');
            this.selected($link);
            this.load($link);
        };
        this.get_selected = function() {
            var k = 0;
            $.each(this.nodes.$files.find('a.file'), function(i, el) {
                if ($(el).hasClass("selected")) {
                   k = i;
                }
            });
            return k;
        };
        this.toggle_wrap = function(state) {
            /* Toggles the content wrap in the page, starts off wrapped */
            this.wrapped = (state == 'wrap' || !this.wrapped);
            $('code').toggleClass('unwrapped');
        };
        this.toggle_files = function(action) {
            var collapse = null;
            if (action == 'hide')
                collapse = true;
            else if (action == 'show')
                collapse = false;

            $('#file-viewer').toggleClass('collapsed-files', collapse);
        };
        this.toggle_known = function(hide) {
            if (hide == null)
                hide = storage.get('files/hide-known');
            else
                storage.set('files/hide-known', hide ? 'true' : '');

            $('#file-viewer').toggleClass('hide-known-files', !!hide);
            var known = $('#toggle-known');
            if (known.length) {
                known[0].checked = !!hide;
            }
        };
        this.next_changed = function(offset) {
            var $files = this.nodes.$files.find('a.file'),
                selected = $files[this.get_selected()],
                isDiff = $('#diff').length,
                filter = (isDiff ? '.diff' : '') + ':not(.known)';

            var list = [];
            $files.each(function() {
                var $file = $(this);
                if (this == selected) {
                    list = [selected];
                } else if (($file.is('.notice, .warning, .error') ||
                            config.needreview_pattern.test($file.attr('data-short'))) &&
                           $file.is(filter)) {
                    list.push(this);
                }
            });

            list = list.slice(offset);
            if (list.length) {
                this.select($(list[0]));
                var $top = $("#top");
                if ($top.length) {
                    $top[0].scrollIntoView(true);
                }
            }
        };
        this.next_delta = function(forward) {
            var $lines, $deltas;

            if ($("#diff").length) {
                $lines =  $('.td-line-code');
                $deltas = $lines.filter('.add, .delete');
            } else {
                $lines = $('.td-line-number >.line');
                $deltas = $lines.filter('.warning, .notice, .error');
            }

            $lines.indexOf = Array.prototype.indexOf;
            if (forward) {
                var height = $(window).height();
                for (var i = 0; i < $deltas.length; i++) {
                    var span = $deltas[i];
                    if (span.getBoundingClientRect().bottom > height) {
                        span = $lines[Math.max(0, $lines.indexOf(span) - config.diff_context)];
                        span.scrollIntoView(true);
                        return;
                    }
                }

                this.next_changed(1);
            } else {
                var res;
                for (var k = 0; k < $deltas.length; k++) {
                    var span_two = $deltas[k];
                    if (span_two.getBoundingClientRect().top >= 0) {
                        break;
                    }
                    res = span_two;
                }

                if (!res) {
                    this.next_changed(-1);
                } else {
                    res = $lines[Math.min($lines.length - 1, $lines.indexOf(res) + config.diff_context)];
                    res.scrollIntoView(false);
                }
            }
        };
    }

    var viewer = new Viewer(),
        storage = z.Storage();

    if (viewer.nodes.$files.find('li').length == 1) {
        viewer.toggle_files('hide');
        $('#files-down, #files-up, #files-expand-all').hide();
    }

    viewer.nodes.$files.find('.directory').click(_pd(function() {
        viewer.toggle_leaf($(this));
    }));

    $(window).resize(_.throttle(function() { viewer.update_viewport(true); }, 10))
             .scroll(_.throttle(function() { viewer.update_viewport(false); }, 10));

    $('#toggle-known').change(function () { viewer.toggle_known(this.checked); });
    viewer.toggle_known();

    $('#files-up').click(_pd(function() {
        viewer.next_changed(-1);
    }));

    $('#files-down').click(_pd(function() {
        viewer.next_changed(1);
    }));

    $('#files-change-prev').click(_pd(function() {
        viewer.next_delta(false);
    }));

    $('#files-change-next').click(_pd(function() {
        viewer.next_delta(true);
    }));

    $('#files-wrap').click(_pd(function() {
        viewer.toggle_wrap();
    }));

    $('#files-hide').click(_pd(function() {
        viewer.toggle_files();
    }));

    $('#files-expand-all').click(_pd(function() {
        viewer.nodes.$files.find('a.closed').each(function() {
            viewer.show_leaf($(this));
        });
    }));

    var file_metadata = $('#metadata').data();

    if (file_metadata.annotateUrl) {
        $('#file-viewer').delegate('.ignore-duplicates-checkbox', 'change',
                                   function(event) {
            var $target = $(event.target);
            $.ajax({type: 'POST',
                    url: file_metadata.annotateUrl,
                    data: { message: $target.attr('name'),
                            ignore_duplicates: $target.prop('checked') || undefined },
                    dataType: 'json'})
        });
    }

    if (file_metadata.automatedSigning) {
        $('#signing-hide-unnecessary, #signing-hide-ignored').change(function() {
            viewer.update_message_filters();
        });
    }

    if (file_metadata.validation) {
        viewer.update_validation({validation: file_metadata.validation,
                                  error: null}, true);
    } else if (file_metadata.validateUrl) {
        $('#validating').css('display', 'block');

        $.ajax({type: 'POST',
                url: file_metadata.validateUrl,
                data: {},
                success: function(data) {
                    if (typeof data != "object")
                        data = { error: data };
                    viewer.update_validation(data);
                },
                error: function(XMLHttpRequest, textStatus, errorThrown) {
                    viewer.update_validation({ error: errorThrown });
                },
                dataType: 'json'
        });
    }

    viewer.nodes.$files.find('.file').click(_pd(function() {
        viewer.select($(this));
        viewer.toggle_wrap('wrap', true);
    }));

    $(window).bind('popstate', function() {
        if (viewer.last != location.pathname) {
            viewer.nodes.$files.find('.file').each(function() {
                if ($(this).attr('href') == location.pathname) {
                    if (!$(this).is('.selected')) {
                        viewer.select($(this));
                    }
                }
            });
        }
    });

    var prefixes = {},
        keys = {};
    $('#commands code').each(function() {
        var $code = $(this),
            $link = $code.parents('tr').find('a'),
            key = $code.text();

        keys[key] = $link;
        for (var i = 1; i < key.length; i++) {
            prefixes[key.substr(0, i)] = true;
        }
    });

    var buffer = '';
    $(document).bind('keypress', function(e) {
        if (e.charCode && !(e.altKey || e.ctrlKey || e.metaKey) &&
                ![HTMLInputElement, HTMLSelectElement, HTMLTextAreaElement]
                    .some(function (iface) { return e.target instanceof iface })) {
            buffer += String.fromCharCode(e.charCode);
            if (keys.hasOwnProperty(buffer)) {
                e.preventDefault();
                keys[buffer].click();
            } else if (prefixes.hasOwnProperty(buffer)) {
                e.preventDefault();
                return;
            }
        }

        buffer = '';
    });

    var stylesheet = $('<style>').attr('type', 'text/css').appendTo($('head'))[0].sheet;
    if (stylesheet && stylesheet.insertRule) {
        stylesheet.insertRule('td.code, #diff, #content {}', 0);

        var rule = stylesheet.cssRules[0],
            tabstopsKey = 'apps/files/tabstops',
            localTabstopsKey = tabstopsKey + ':' + $('#metadata').attr('data-slug');

        $("#tab-stops-container").show();

        var $tabstops = $('#tab-stops')
            .numberInput(4)
            .val(Number(storage.get(localTabstopsKey) || storage.get(tabstopsKey)) || 4)
            .change(function(event, global) {
                rule.style.tabSize = rule.style.MozTabSize = $(this).val();
                if (!global)
                    storage.set(localTabstopsKey, $(this).val());
                storage.set(tabstopsKey, $(this).val());
            })
            .trigger('change', true);
    }

    return viewer;
}

var viewer = null;
$(document).ready(function() {
    var nodes = { root: '#file-viewer', files: '#files', thinking: '#thinking', commands: '#commands' };
    function poll_file_extraction() {
        $.getJSON($('#extracting').attr('data-url'), function(json) {
            if (json && json.status) {
                $('#file-viewer').load(window.location.pathname + '?full=yes' + ' #file-viewer', function() {
                    $(this).children().unwrap();
                    viewer = bind_viewer(nodes);
                    viewer.selected(viewer.nodes.$files.find('a.selected'));
                    viewer.compute($('#content-wrapper'));
                });
            } else if (json) {
                var errors = false;
                $.each(json.msg, function(k) {
                    if (json.msg[k] !== null) {
                        errors = true;
                        $('<p>').text(json.msg[k]).appendTo($('#file-viewer div.error'));
                    }
                });
                if (errors) {
                    $('#file-viewer div.error').show();
                    $('#extracting').hide();
                } else {
                    setTimeout(poll_file_extraction, 2000);
                }
            }
        });
    }

    if ($('#extracting').length) {
        poll_file_extraction();
    } else if ($('#file-viewer').length) {
        viewer = bind_viewer(nodes);
        viewer.selected(viewer.nodes.$files.find('a.selected'));
        viewer.compute($('#content-wrapper'));
    }

    var $left = $('#id_left'),
        $right = $('#id_right');

    $left.find('option:not([value])').attr('disabled', true);

    var $left_options = $left.find('option:not([disabled])'),
        $right_options = $right.find('option:not([disabled])');

    $right.change(function(event) {
        var right = $right.val();
        $left_options.attr('disabled', function() { return this.value == right; });
    }).change();
    $left.change(function(event) {
        var left = $left.val();
        $right_options.attr('disabled', function() { return this.value == left; });
    }).change();
});
