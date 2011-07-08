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
                        html.push('+ ' + lines[t] + '\n');
                        break;
                    case DIFF_DELETE:
                        html.push('- ' + lines[t] + '\n');
                        break;
                    case DIFF_EQUAL:
                        html.push('  ' + lines[t] + '\n');
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
    SyntaxHighlighter.amo_vars = {'deletions': {}, 'additions': {}, 'is_diff': false};

    SyntaxHighlighter.Highlighter.prototype.getLineNumbersHtml = function(code, lineNumbers) {
        /* Make syntax highlighter produce line numbers with links and
         * classes in  them. */
        var html = '',
            count = code.split('\n').length,
            normal_count = 1,
            deleted_count = 1;
        /* The line numbers get tricky, but we set to add or delete and track
         * those so that the diff bar will work */
        for (var i = 0; i < count; i++) {
            var classes = '';
            if (SyntaxHighlighter.amo_vars.deletions['index'+i] !== undefined) {
                classes = 'delete';
                html += this.getLineHtml(i, i+1, format('<a id="D{0}" class="{1}" href="#D{0}"> </a>', deleted_count++, classes));
            } else {
                if (SyntaxHighlighter.amo_vars.additions['index'+i] !== undefined) {
                    classes = 'add';
                }
                html += this.getLineHtml(i, i+1, format('<a id="L{0}" class="{1}" href="#L{0}">{0}</a>', normal_count++, classes));
            }
        }
        return html;
    };

    SyntaxHighlighter.Highlighter.prototype.getLineHtml = function(lineIndex, lineNumber, code)	{
        var classes = [
            'original',
            'line',
            'number' + lineNumber,
            'index' + lineIndex,
            'alt' + (lineNumber % 2 === 0 ? 1 : 2).toString()
        ];

        if (this.isLineHighlighted(lineNumber)) {
            classes.push('highlighted');
        }

        if (lineNumber === 0) {
            classes.push('break');
        }

        /* HTML parsing with regex warning disclaimer. This lib writes out
         * well formed lines with <code> and <a>. We want a hint
         * of the line length without all the syntax highlighting in it. */
        var raw = code.replace(/<.*?>/g, '').replace(/&.*?;/g, ' ');
        if (raw.length > 80) {
            classes.push('longline');
        }

        /* For diffs we have to do more work to make the line numbers
         * do what we'd like. */
        if (SyntaxHighlighter.amo_vars.is_diff) {
            /* Spot delete alter class and add to object */
            if (code.match(/<code class=".*?comments.*?">/)) {
                SyntaxHighlighter.amo_vars.deletions['index'+lineIndex] = true;
                classes.push('delete');
            }

            /* Spot add, alter class and add to object */
            if (code.match(/<code class=".*?string.*?">/)) {
                SyntaxHighlighter.amo_vars.additions['index'+lineIndex] = true;
                classes.push('add');
            }
        }
        return '<div class="' + classes.join(' ') + '">' + code + '</div>';
    };
}

jQuery.fn.numberInput = function(increment) {
    this.each(function() {
        var $self = $(this);
        $self.addClass("number-combo-input");

        var height = $self.outerHeight() / 2;

        var $dom = $('<span>').attr({ 'class': 'number-combo' })
                     .append($('<a>').attr({ 'class': 'number-combo-button-down',
                                             'href': '#' })
                                     .text('↓'))
                     .append($('<a>').attr({ 'class': 'number-combo-button-up',
                                             'href': '#' })
                                     .text('↑'));

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
                $self.val($self.val().replace(/\D+/, ""));
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

function bind_viewer(nodes) {
    $.each(nodes, function(x) {
        nodes['$'+x] = $(nodes[x]);
    });
    function Viewer() {
        this.nodes = nodes;
        this.wrapped = true;
        this.hidden = false;
        this.top = null;
        this.last = null;
        this.fix_vertically = function($inner, $outer) {
            var $self = this;
            if (!$self.top) {
                $self.top = $outer.position().top;
            }
            function update() {
                var sb_bottom = $self.top + $outer.height() - $inner.height();
                if ($(window).scrollTop() > sb_bottom) {
                    $inner.css({'position': 'absolute', 'top': sb_bottom});
                } else if ($(window).scrollTop() > $self.top) {
                    $inner.css({'position': 'fixed', 'top': 0});
                } else {
                    $inner.css({'position': 'absolute', 'top': $self.top});
                }
            }
            $(window).scroll(debounce(update), 200);
            update();
        };
        this.size_line_numbers = function($node, deleted) {
            /* We need to re-size the line numbers correctly depending upon
               the wrapping. */

            var self = this;
            $node.each(function(){
                var $self = $(this),
                    long_lines = $(this).find('td.code div.longline');
                /* Use the longline hint to guess at long lines and
                 * see what needs resizing. */
                $.each(long_lines, function() {
                    var $this = $(this),
                        k = parseInt($this.attr('class').match(/index(\d+)/)[1], 10);
                    $self.find('td.gutter div.index' + k).css('height',  $this.height() + 'px');
                });
            });
            this.updateViewport(true);
        };
        this.compute = function(node) {
            var $diff = node.find('#diff'),
                $content = node.find('#content');

            if ($content && !$diff.length) {
                SyntaxHighlighter.highlight($content);
                // Note SyntaxHighlighter has nuked the node and replaced it.
                this.size_line_numbers(node.find('#content'), false);
            }

            if ($diff.length) {
                var dmp = new diff_match_patch();
                // Line diffs http://code.google.com/p/google-diff-match-patch/wiki/LineOrWordDiffs
                var a = dmp.diff_linesToChars_($diff.siblings('.right').text(), $diff.siblings('.left').text());
                var diffs = dmp.diff_main(a[0], a[1], false);
                dmp.diff_charsToLines_(diffs, a[2]);
                $diff.text(dmp.diff_prettyHtml(diffs)).show();

                /* Reset the syntax highlighter variables. */
                SyntaxHighlighter.amo_vars = {'deletions': {}, 'additions': {}, 'is_diff': true};
                SyntaxHighlighter.highlight($diff);
                // Note SyntaxHighlighter has nuked the node and replaced it.
                $diff = node.find('#diff');
                this.size_line_numbers($diff, true);

                /* Build out the diff bar based on the line numbers. */
                var $sb = $diff.siblings('.diff-bar').eq(0),
                    $gutter = $diff.find('td.gutter'),
                    $lines = $gutter.find('div.line a');

                if ($lines.length) {
                    var flush = function($line, bottom) {
                        var height = (bottom - $start.offset().top) * 100 / $gutter.height(),
                            style = { 'height': height + "%" };

                        if ($prev && !$prev.attr('class')) {
                            style['border-top-width'] = '1px';
                            style['margin-top'] = '-1px';
                        }
                        if ($line && !$line.attr('class')) {
                            style['border-bottom-width'] = '1px';
                            style['margin-bottom'] = '-1px';
                        }

                        $sb.append($('<a>', { 'href': $start.attr('href'), 'class': $start.attr('class'),
                                              'css': style }));

                        $prev = $start;
                        $start = $line;
                    };

                    var $prev, $start = null;
                    $lines.each(function () {
                        var $line = $(this);
                        if (!$start) {
                            $start = $line;
                        } else if ($line.attr('class') != $start.attr('class')) {
                            flush($line, $line.offset().top);
                        }
                    });
                    flush(null, $gutter.offset().bottom);

                    this.$diffbar = $sb;
                    this.$viewport = $('<div>', { 'class': 'diff-bar-viewport' });
                    this.$gutter = $gutter;
                    $sb.append(this.$viewport);

                    $diff.addClass('diff-bar-height');
                    $sb.show();

                    this.updateViewport(true);
                }
            }

            if (window.location.hash && window.location.hash != 'top') {
                window.location = window.location;
            }
        };
        this.updateViewport = function(resize) {
            var $viewport = this.$viewport,
                $gutter = this.$gutter,
                $diffbar = this.$diffbar;

            if (!$viewport) {
                return;
            }

            var gutter = $gutter[0].getBoundingClientRect(),
                gutter_height = gutter.bottom - gutter.top,
                window_height = $(window).height(),
                diffbar_top = -Math.min(0, gutter.top) * 100 / gutter_height + "%";

            if (resize) {
                var height = gutter_height + Math.min(0, gutter.top) - Math.max(gutter.bottom - window_height, 0);

                $viewport.css({ 'height': height * 100 / gutter_height + "%", 'top': diffbar_top });

                $diffbar.css({ 'height': Math.min($("#diff-wrapper").height(), window_height) + "px" });
            } else {
                $viewport.css({ 'top': diffbar_top });
            }

            if (gutter.bottom <= window_height) {
                $diffbar.css({ 'position': 'absolute', 'top': '', 'bottom': '0' });
            } else if (gutter.top > 0) {
                $diffbar.css({ 'position': 'absolute', 'top': '0', 'bottom': '' });
            } else {
                $diffbar.css({ 'position': 'fixed', 'top': '0px', 'bottom': '' });
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
        };
        this.load = function($link) {
            /* Accepts a jQuery wrapped node, which is part of the tree.
               Hides content, shows spinner, gets the content and then
               shows it all. */
            var self = this,
                $old_wrapper = $('#content-wrapper');
            $old_wrapper.hide();
            this.nodes.$thinking.show();
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
                        if (self.hidden) {
                            self.toggle_files('hide');
                        }
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
            this.size_line_numbers($('#content-wrapper'), false);
        };
        this.toggle_files = function(state) {
            this.hidden = (state == 'hide' || !this.hidden);
            if (this.hidden) {
                this.nodes.$files.hide();
                this.nodes.$commands.detach().appendTo('div.featured-inner:first');
                this.nodes.$thinking.addClass('full');
            } else {
                this.nodes.$files.show();
                this.nodes.$commands.detach().appendTo(this.nodes.$files);
                this.nodes.$thinking.removeClass('full');
            }
            $('#content-wrapper').toggleClass('full');
            this.size_line_numbers($('#content-wrapper'), false);
        };
        this.next_changed = function(offset) {
            var $files = this.nodes.$files.find('a.file'),
                selected = $files[this.get_selected()],
                isDiff = $('#diff').length;

            var a = [], list = a;
            $files.each(function () {
                if (this == selected) {
                    list = [selected];
                } else if (config.needreview_pattern.test($(this).attr('data-short')) && (!isDiff || $(this).hasClass('diff'))) {
                    list.push(this);
                }
            });

            list = list.concat(a).slice(offset);
            if (list.length) {
                this.select($(list[0]));
                $("#top")[0].scrollIntoView(true);
            }
        };
        this.next_delta = function(forward) {
            var $deltas = $('td.code .line.add, td.code .line.delete'),
                $lines = $('td.code .line');
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

    var viewer = new Viewer();

    if (viewer.nodes.$files.find('li').length == 1) {
        viewer.toggle_files();
        $('#files-down').parent().hide();
        $('#files-up').parent().hide();
        $('#files-expand-all').parent().hide();
    }

    viewer.nodes.$files.find('.directory').click(_pd(function() {
        viewer.toggle_leaf($(this));
    }));

    if ($('#diff').length) {
        $(window).resize(debounce(function () { viewer.updateViewport(true); }));
        $(window).scroll(debounce(function () { viewer.updateViewport(false); }));
    }

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

    viewer.nodes.$files.find('.file').click(_pd(function() {
        viewer.select($(this));
        viewer.toggle_wrap('wrap');
    }));

    $(window).bind('popstate', function() {
        if (viewer.last != location.pathname) {
            viewer.nodes.$files.find('.file').each(function() {
                if ($(this).attr('href') == location.pathname) {
                    viewer.select($(this));
                }
            });
        }
    });

    var prefixes = {},
        keys = {};
    $('#commands code').each(function () {
        var $code = $(this),
            $link = $code.parents('tr').find('a'),
            key = $code.text();

        keys[key] = $link;
        for (var i = 1; i < key.length; i++) {
            prefixes[key.substr(0, i)] = true;
        }
    });

    var buffer = '';
    $(document).bind('keypress', _pd(function(e) {
        if (e.charCode) {
            buffer += String.fromCharCode(e.charCode);
            if (keys.hasOwnProperty(buffer)) {
                keys[buffer].click();
            } else if (prefixes.hasOwnProperty(buffer)) {
                return;
            }
        }

        buffer = '';
    }));

    var stylesheet = $('<style>').attr('type', 'text/css').appendTo($('head'))[0].sheet;
    if (stylesheet && stylesheet.insertRule) {
        stylesheet.insertRule('td.code, #diff, #content {}', 0);

        var rule = stylesheet.cssRules[0],
            tabstopsKey = 'apps/files/tabstops',
            localTabstopsKey = tabstopsKey + ':' + $('#metadata').attr('data-slug'),
            storage = z.Storage();

        $("#tab-stops-container").show();

        var $tabstops = $('#tab-stops')
            .numberInput(4)
            .val(Number(storage.get(localTabstopsKey) || storage.get(tabstopsKey)) || 4)
            .change(function() {
                rule.style.tabSize = rule.style.MozTabSize = $(this).val();
                storage.set(localTabstopsKey, $(this).val());
                storage.set(tabstopsKey, $(this).val());
            })
            .change();
    }

    return viewer;
}

$(document).ready(function() {
    var viewer = null;
    var nodes = { files: '#files', thinking: '#thinking', commands: '#commands' };
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
});
