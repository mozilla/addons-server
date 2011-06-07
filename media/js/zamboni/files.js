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
                   Unless the diff line question does not have a new line on
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
        this.line_wrap = function($node, deleted) {
            /* SyntaxHighlighter doesn't produce linked line numbers or cope
               with wrapped text producing bigger line numbers.
               This fixes that. */
            var line_numbers = 1,
                deleted_line_numbers = 1;
            $node.each(function(){
                var $self = $(this),
                    $gutter = $self.find('td.gutter');
                    $code = $self.find('td.code');
                $gutter.find('div.line').each(function(i){
                    var $gutter_line = $(this),
                        $line = $code.find('.line:nth-child(' + (i+1) +')'),
                        height = $line.height(),
                        del = !!$line.children('code.comments').length,
                        link = $gutter_line.children('a');
                    /* If there's a deleted line, don't show a line number */
                    if (deleted && del) {
                        $gutter_line.html($('<a>', {'href': '#D' + deleted_line_numbers,
                                                    'name': 'D' + deleted_line_numbers,
                                                    'class': 'delete',
                                                    'style': 'height: ' + height + 'px',
                                                    'text': ' '}));
                        $line.addClass('delete');
                        deleted_line_numbers++;
                        return;
                    }
                    /* If a link already exists and the height is different
                       alter it. */
                    if (link.length) {
                        if (link.height() != height) {
                            link.css('height',  height + 'px');
                        }
                    } else {
                        /* Otherwise add in a link, occurs on first pass. */
                        var klass = $line.find('code.string').length ? 'add' : '';
                        $gutter_line.html($('<a>', {'href': '#L' + line_numbers,
                                                    'name': 'L' + line_numbers,
                                                    'class': klass,
                                                    'style': 'height: ' + height + 'px',
                                                    'text': line_numbers}));
                        $line.addClass(klass);
                        line_numbers++;
                    }
                });
            });
        };
        this.compute = function(node) {
            var $diff = node.find('#diff');

            if (node.find('#content') && !$diff.length) {
                SyntaxHighlighter.highlight();
                // Fix up the lines to be the way we want.
                // Note SyntaxHighlighter has nuked the node and replaced it.
                this.line_wrap(node.find('#content'), false);
            }

            if ($diff.length) {
                var dmp = new diff_match_patch();
                // Line diffs http://code.google.com/p/google-diff-match-patch/wiki/LineOrWordDiffs
                var a = dmp.diff_linesToChars_($diff.siblings('.right').text(), $diff.siblings('.left').text());
                var diffs = dmp.diff_main(a[0], a[1], false);
                dmp.diff_charsToLines_(diffs, a[2]);
                $diff.text(dmp.diff_prettyHtml(diffs)).show();

                SyntaxHighlighter.highlight();
                // Note SyntaxHighlighter has nuked the node and replaced it.
                $diff = node.find('#diff');
                this.line_wrap($diff, true);

                /* Build out the diff bar based on the line numbers. */
                var $sb = $diff.siblings('.diff-bar').eq(0),
                    $lines = $diff.find('td.gutter div.line a');

                if ($lines.length) {
                    var state = {'start':0, 'type':$lines.eq(0).attr('class'),
                                 'href':$lines.eq(0).attr('href')};
                    for (var j = 1; j < $lines.length; j++) {
                        var $node = $lines.eq(j);
                        if (!$node.hasClass(state.type)) {
                            this.side_bar_append($sb, state, j, $lines.length);
                            state = {'start': j, 'type': $node.attr('class'),
                                     'href': $node.attr('href')};
                        }
                    }
                    $diff.addClass('diff-bar-height');
                    this.side_bar_append($sb, state, j, $lines.length);
                    this.fix_vertically($sb, $diff);
                    $sb.show();
                }
            }

            if (window.location.hash && window.location.hash != 'top') {
                window.location = window.location;
            }
        };
        this.side_bar_append = function($sb, state, k, total) {
            $sb.append($('<a>', {'href': state.href, 'class': state.type,
                                 'css': {'height': (((k-state.start)/total) * 100) + '%' }}));
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
            $old_wrapper.load($link.attr('href').replace('/file/', '/fragment/') + ' #content-wrapper', function() {
                $(this).children().unwrap();
                var $new_wrapper = $('#content-wrapper');
                self.compute($new_wrapper);
                self.nodes.$thinking.hide();
                $new_wrapper.slideDown();
                if (self.hidden) {
                    self.toggle_files('hide');
                }
            });
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
            /* Toggles the content wrap in the page, starts off unwrapped */
            this.wrapped = (state == 'wrap' || !this.wrapped);
            $('code').toggleClass('wrap-toggle');
            this.line_wrap($('#content-wrapper'));
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

    $('#files-up').click(_pd(function() {
        var prev = viewer.get_selected() - 1;
        if (prev >= 0) {
            viewer.select(viewer.nodes.$files.find('a.file').eq(prev));
        }
    }));

    $('#files-down').click(_pd(function() {
        var next = viewer.nodes.$files.find('a.file').eq(viewer.get_selected() + 1);
        if (next.length) {
            viewer.select(next);
        }
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

    $(document).bind('keyup', _pd(function(e) {
        if (e.keyCode == 72) {
            $('#files-hide').trigger('click');
        } else if (e.keyCode == 75) {
            $('#files-up').trigger('click');
        } else if (e.keyCode == 74) {
            $('#files-down').trigger('click');
        } else if (e.keyCode == 87) {
            $('#files-wrap').trigger('click');
        } else if (e.keyCode == 69) {
            $('#files-expand-all').trigger('click');
        }
    }));
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
