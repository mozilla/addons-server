"use strict";

var Highlighter = {
    squash_space: function squash_space(str) {
        // Squash non-significant whitespace in a string, so it can be
        // ignored for the sake of diffs.
        return str.replace(/[^\n]+/g, function (match) {
            return match.trim()
                .replace(/\s+/g, ' ')
                .replace(/([^a-z0-9_$]) | (?![a-z0-9_$])/gi, "$1");
        })
    },

    diff: function diff(left, right, brush) {
        // Creates a unified diff of the arbitrary strings `left` and
        // `right`, ignoring white-space changes within lines..

        var differ = new diff_match_patch();

        // Start by squashing the whitespace in both input strings,
        // and converting them to arrays of characters.
        var charred_inputs = differ.diff_linesToChars_(
            this.squash_space(right), this.squash_space(left));

        // Then have the diff library diff thos.
        var diffs = differ.diff_main(charred_inputs[0],
                                     charred_inputs[1], false);

        // And convert them back to lines.
        differ.diff_charsToLines_(diffs, charred_inputs[2]);

        // If we have a brush, filter the left lines through the syntax
        // highlighter. Otherwise, just escape them.
        if (brush) {
            var left_lines = this.highlight_lines(left, brush);
        } else {
            left_lines = _.map(left.split('\n'), _.escape);
        }
        var right_lines = _.map(right.split('\n'), _.escape);;

        // And finally convert that to a unified diff, restoring the
        // original white-space.
        // Note that, for historic reasons, the diff library has a
        // different opinion on what constitutes left and right than we
        // do.
        var classes = {'-': 'delete', '+': 'add', ' ': ''};

        function output(line_no, op, line) {
            // Wrap a line in HTML and append a metadata object to our
            // output.
            var html = format('<code class="plain">{op}{line}</code>',
                              {op: op, line: line});

            result.push({
                number: line_no,
                'class': classes[op],
                code: html
            });
        }

        var result = [];
        var left_line = 0;
        var right_line = 0;

        for (var i = 0; i < diffs.length; i++) {
            // Each element in `diffs` is an addition, a removal, or
            // common fragment, and may contain multiple lines.
            var op = diffs[i][0];
            // Strip off the last \n of the group and split into lines.
            var lines = diffs[i][1].replace(/\n$/, "").split('\n');

            for (var j = 0; j < lines.length; j++) {
                switch (op) {
                case DIFF_DELETE:
                    // A removal. Take a line from the right.
                    output('', '-', right_lines[right_line])
                    right_line += 1;
                    break;

                case DIFF_EQUAL:
                    // A Common line. Take a line from the left,
                    // but increment both counters.
                    output(left_line + 1, ' ', left_lines[left_line]);
                    left_line += 1;
                    right_line += 1;
                    break;

                case DIFF_INSERT:
                    // An insert. Take a line from the left.
                    output(left_line + 1, '+', left_lines[left_line]);
                    left_line += 1;
                    break;

                default:
                    throw 'an unexpected fit';
                }
            }
        }

        return result;
    },

    highlight_lines: function highlight_lines(text, brush) {
        // Highlight the given text with the brush `brush`,
        // and return the resulting lines.

        // This involves a lot of hackery to deal with the `shCore`
        // library.

        // Create an element containing the text we want to diff,
        // and put it inside another element, since the syntax
        // highlighter will try to replace the original element in the
        // DOM when it's done.

        // Verify that we actually support the used brush
        // see https://github.com/mozilla/addons-server/issues/4552 for more
        // details. This shows an alert if a brush is not supported.
        var discoveredBrushes = SyntaxHighlighter.brushes;

        if (discoveredBrushes) {
            var brushes = [];

            for (var discoveredBrush in discoveredBrushes) {
                var aliases = discoveredBrushes[discoveredBrush].aliases;

                if (aliases == null) {
                    continue;
                }

                for (var i = 0, l = aliases.length; i < l; i++) {
                    brushes.push(aliases[i]);
                }
            }

            if (!brushes.includes(brush.toLowerCase())) {
                $('.highlighter-output-broken').modal('', { width: 960 }).render();
                $('.highlighter-output-broken').toggleClass('js-hidden');
            }
        }

        var $node = $('<pre>', {'class': format('brush: {0}; toolbar: false;',
                                                [brush]),
                                text: text});
        $('<div>').append($node);

        var output = [];
        SyntaxHighlighter.amo_vars = {'lines': output};
        SyntaxHighlighter.highlight({}, $node[0]);

        // At this point, we have the highlighted lines in the `output`
        // array.
        return output;
    },

    highlight: function highlight($node) {
        // Do not use `.data()` for these. jQuery will attempt
        // to parse them as JSON if they start with `{` or `[`.
        var brush = $node.data('brush');

        if ($node.is('[data-content]')) {
            var content = $node.attr('data-content');

            var lines = _.map(this.highlight_lines(content, brush), function(line, idx) {
                return {
                    number: idx + 1,
                    classes: '',
                    code: line
                };
            });
        } else {
            // Diff.
            var left = $node.attr('data-left');
            var right = $node.attr('data-right');

            var lines = this.diff(left, right, brush);
        }

        // Annotate the lines a bit.
        var deleted_line = 0;
        _.each(lines, function(line) {
            if (line.number) {
                line.id = "L" + line.number;
            } else {
                deleted_line++;
                line.id = "D" + deleted_line;
            }
        });

        var line_order = Math.ceil(Math.log(lines.length) / Math.log(10));
        // Width of the line numbers column.
        // 1.2 ex width per digit, just to be safe, and an additional 4 for padding.
        var lines_width = 1.2 * line_order + 4;

        var html = syntaxhighlighter_template({lines: lines});

        $node.html(html);
        $node.find('.highlighter-column-line-numbers').css('width', lines_width + 'ex');
    },
};

_.extend(_.templateSettings, {
    evaluate:    /\{%([^]+?)%\}/g,
    escape:      /\{\{([^]+?)\}\}/g
});

var config = {
    diff_context: 2,
    needreview_pattern: /\.(js|jsm|xul|xml|x?html?|manifest|sh|py)$/i
};

if (typeof SyntaxHighlighter !== 'undefined') {
    /* Turn off double click on the syntax highlighter. */
    SyntaxHighlighter.defaults['quick-code'] = false;
    SyntaxHighlighter.defaults['auto-links'] = false;

    SyntaxHighlighter.Highlighter.prototype.getLineHtml = function(lineIndex, lineNumber, code) {
        // We're just after HTML for individual lines here. Don't bother
        // doing anything aside from storing it.

        if (lineIndex == 0) {
            // See comment in getHtml.
            code = code.replace(/(^|>)\|/, '');
        }

        SyntaxHighlighter.amo_vars.lines[lineIndex] = code;
    };

    SyntaxHighlighter.Highlighter.prototype.getHtml = function(code) {
        // Just the bare minimum we need to get the HTML for individual
        // lines.
        //
        // Much of this comes from the original:
        //   https://github.com/mozilla/olympia/blob/a35ab083/static/js/lib/syntaxhighlighter/shCore.js#L1552

        // find matches in the code using brushes regex list
        var matches = this.findMatchesNew(this.regexList, code);

        // processes found matches into the html
        var html = this.getMatchesHtml(code, matches);

        // N.B.(Kris): This... unbelievably... trims whitespace from both
        // sides of the output, even though it was already trimmed
        // prior to output in the stock version of this function.
        html = '|' + html;
        this.getCodeLinesHtml(html);

        // And we're done. The line HTML is now in `SyntaxHighlighter.amo_vars.lines`.
    };

    // Urgh. Why, oh why, with the absurd Crockford Closures...
    // I shouldn't have to do this.
    //
    // Slightly modified from the built-in version to handle
    // newer keywords:
    new function() {
        function JSBrush() {
            var keywords = 'break case catch class const continue debugger' +
                           'default delete do else enum export extends false finally ' +
                           'for function if implements import in instanceof ' +
                           'interface let new null package private protected public' +
                           'static return super switch this throw true try typeof ' +
                           'var void while with yield';

            var r = SyntaxHighlighter.regexLib;

            this.regexList = [
                { regex: r.multiLineDoubleQuotedString,                 css: 'string' },            // double quoted strings
                { regex: r.multiLineSingleQuotedString,                 css: 'string' },            // single quoted strings
                { regex: /`([^`])*`/g,                                  css: 'string' },            // template literals
                { regex: r.singleLineCComments,                         css: 'comments' },          // one line comments
                { regex: r.multiLineCComments,                          css: 'comments' },          // multiline comments
                { regex: /\s*#.*/gm,                                    css: 'preprocessor' },      // preprocessor tags like #region and #endregion
                { regex: new RegExp(this.getKeywords(keywords), 'gm'),  css: 'keyword' }            // keywords
                ];

            this.forHtmlScript(r.scriptScriptTags);
        };
        JSBrush.aliases = ['js', 'jsm', 'es'];
        JSBrush.prototype = SyntaxHighlighter.brushes.JScript.prototype;
        SyntaxHighlighter.brushes.JScript = JSBrush;
    };
}

jQuery.fn.numberInput = function(increment) {
    this.each(function() {
        var $self = $(this);
        $self.addClass("number-combo-input");

        var height = $self.outerHeight() / 2;

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
            $self.on(event, function() {
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
            var contentElem = node.find('#diff, #content');
            if (contentElem.length) {
                Highlighter.highlight(contentElem);
            }

            this.compute_messages(node);

            if (window.location.hash && window.location.hash != 'top') {
                window.location = window.location;
            }

            this.show_selected();
        };
        this.update_message_filters = function() {
            var $root = this.nodes.$root;
            $root.toggleClass('messages-duplicate', !this.hideIgnored);
            $root.toggleClass('messages-all');
        };
        this.message_type_map = {
            'error': 'error',
            'warning': 'warning',
            'notice': 'info'
        };
        this.message_classes = function(message, base_class) {
            base_class = base_class || '';
            var classes = [''];
            if (message.type == "error") {
                if (message.ignored) {
                    classes.push('-ignored');
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
                }
            }
            this.update_viewport(true);
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

                    $.each(['warning', 'warning-signing',
                            'error', 'error-signing',
                            'notice', 'notice-signing'], function(i, type) {
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
                var offset = $sel.position().top + $sel.outerHeight() - $cont[0].clientHeight;
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

    $(window).on('popstate', function() {
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
    $(document).on('keypress', function(e) {
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

    var tabSizeDependentNodes = $('td.code, #diff, #content');
    var tabstopsKey = 'apps/files/tabstops',
        localTabstopsKey = tabstopsKey + ':' + $('#metadata').attr('data-slug');

    $("#tab-stops-container").show();

    var $tabstops = $('#tab-stops')
        .numberInput(4)
        .val(Number(storage.get(localTabstopsKey) || storage.get(tabstopsKey)) || 4)
        .change(function(event, global) {
            tabSizeDependentNodes.css('tab-size', $(this).val());
            tabSizeDependentNodes.css('-moz-tab-size', $(this).val());
            if (!global)
                storage.set(localTabstopsKey, $(this).val());
            storage.set(tabstopsKey, $(this).val());
        })
        .trigger('change', true);

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

                        // The box isn't visible / created if there are errors
                        // so we have to create the notification-box ourselves.
                        $('#validating').after($('<div>', {
                            'class': 'notification-box error',
                            'text': json.msg[k]
                        }));
                    }
                });
                if (errors) {
                    $('.notification-box .error').show();
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

    $left.find('option:not([value])').prop('disabled', true);

    var $left_options = $left.find('option:not([disabled])'),
        $right_options = $right.find('option:not([disabled])');

    $right.change(function(event) {
        var right = $right.val();
        $left_options.prop('disabled', function() { return this.value == right; });
    }).change();
    $left.change(function(event) {
        var left = $left.val();
        $right_options.prop('disabled', function() { return this.value == left; });
    }).change();
});
