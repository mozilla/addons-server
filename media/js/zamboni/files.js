if (typeof diff_match_patch !== 'undefined') {
    diff_match_patch.prototype.diff_prettyHtml = function(diffs) {
        /* An override of prettyHthml from diff_match_patch. This
           one will not put any style attrs in the ins or del. */
        var html = [];
        var k = 1;
        for (var x = 0; x < diffs.length; x++) {
            var op = diffs[x][0];    // Operation (insert, delete, equal)
            var data = diffs[x][1];  // Text of change.
            var text = data.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            /* As as side effect, add in line numbers */
            var lines = text.split('\n');
            if (lines[lines.length-1] === '') {
                lines.pop();
            }
            if (lines[0] === '') {
                lines.splice(0, 1);
            }
            for (var t = 0; t < lines.length; t++) {
                switch (op) {
                    case DIFF_INSERT:
                        // TODO (andym): templates might work here as suggested by cvan
                        html.push(format('<div class="line add"><span class="number"><a href="#L{0}" name="L{0}">{0}</a> +' +
                                         '</span><span class="code">{1}</span></div>', k, lines[t]));
                        k++;
                        break;
                    case DIFF_DELETE:
                        html.push(format('<div class="line delete"><span class="number"> -</span>' +
                                         '<span class="code">{0}</span></div>', lines[t]));
                        break;
                    case DIFF_EQUAL:
                        html.push(format('<div class="line"><span class="number"><a href="#L{0}" name="L{0}">{0}</a>&nbsp;&nbsp;' +
                                         '</span><span class="code">{1}</span></div>', k, lines[t]));
                        k++;
                        break;
                }
            }
        }
        return html.join('');
    };
}

function bind_viewer(nodes) {
    function Viewer() {
        this.nodes = nodes;
        this.wrapped = true;
        this.hidden = false;
        this.compute = function(node) {
            var $content = node.find('#content'),
                $diff = node.find('#diff');
            if ($content.length) {
                var splitted = $content.text().split('\n'),
                    length = splitted.length,
                    html = [];
                if (splitted.slice(length-1) == '') {
                    length = length - 1;
                }
                for (var k = 0; k < length; k++) {
                    if (splitted[k] !== undefined) {
                        var text = splitted[k].replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                        html.push(format('<div class="line"><span class="number"><a href="#L{0}" name="L{0}">{0}</a></span>' +
                                         '<span class="code"> {1}</span></div>', k+1, text));
                    }
                }
                $content.html(html.join('')).removeClass('hidden').show();
            }

            if ($diff.length) {
                var dmp = new diff_match_patch();
                var diff = dmp.diff_main($diff.siblings('.left').text(), $diff.siblings('.right').text());
                $diff.html(dmp.diff_prettyHtml(diff)).removeClass('hidden').show();
            }

            if (window.location.hash) {
                window.location = window.location;
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
                 .closest('li').next('ul')
                 .addClass('hidden').hide();
        };
        this.show_leaf = function($leaf) {
            /* Exposes the leaves for a given set of node. */
            $leaf.removeClass('closed').addClass('open')
                 .closest('li').next('ul')
                 .removeClass('hidden').show();
        };
        this.selected = function($link) {
            /* Exposes all the leaves to an element */
            $link.parentsUntil('ul.root').filter('ul')
                 .removeClass('hidden').show()
                 .each(function() {
                        $(this).prev('li').find('a:first')
                               .removeClass('closed').addClass('open');
            });
        };
        this.load = function($link) {
            /* Accepts a jQuery wrapped node, which is part of the tree.
               Hides content, shows spinner, gets the content and then
               shows it all. Then alters the title. */
            var self = this,
                $old_wrapper = $('#content-wrapper');
            $old_wrapper.hide();
            this.nodes.$thinking.removeClass('hidden').show();
            if (history.pushState !== undefined) {
                history.pushState({ path: $link.text() }, '', $link.attr('href'));
            }
            $old_wrapper.load($link.attr('href') + ' #content-wrapper', function() {
                $(this).children().unwrap();
                var $new_wrapper = $('#content-wrapper');
                self.compute($new_wrapper);
                self.nodes.$thinking.hide();
                $new_wrapper.slideDown();
                if (self.hidden) {
                    self.toggle_files('hide');
                }
            });
            this.nodes.$title.text($link.closest('li').attr('data-short'));
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
            this.wrapped = (state == 'wrap' || !this.wrapped);
            $('pre').toggleClass('wrapped', this.wrapped);
        };
        this.toggle_files = function(state) {
            this.hidden = (state == 'hide' || !this.hidden);
            if (this.hidden) {
                this.nodes.$files.hide();
                this.nodes.$commands.detach().appendTo('#content-wrapper');
            } else {
                this.nodes.$files.show();
                this.nodes.$commands.detach().appendTo('#files');
            }
        };
    }

    var viewer = new Viewer();

    viewer.nodes.$files.find('.directory').click(_pd(function() {
        viewer.toggle_leaf($(this));
    }));

    $('#files-prev').click(_pd(function() {
        viewer.select(viewer.nodes.$files.find('a.file').eq(viewer.get_selected() - 1));
    }));

    $('#files-next').click(_pd(function() {
        viewer.select(viewer.nodes.$files.find('a.file').eq(viewer.get_selected() + 1));
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

    $(document).bind('keyup', _pd(function(e) {
        if (e.keyCode == 72) {
            $('#files-hide').trigger('click');
        } else if (e.keyCode == 75) {
            $('#files-next').trigger('click');
        } else if (e.keyCode == 74) {
            $('#files-prev').trigger('click');
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
    var nodes = {
        $files: $('#files'),
        $thinking: $('#thinking'),
        $title: $('#breadcrumb'),
        $commands: $('#commands')
    };
    function poll_file_extraction() {
        $.getJSON($('#extracting').attr('data-url'), function(json) {
            if (json && json.status) {
                $('#file-viewer').load(window.location.pathname + ' #file-viewer', function() {
                    viewer = bind_viewer(nodes);
                    viewer.selected(viewer.$tree.find('a.selected'));
                    viewer.compute($('#content-wrapper'));
                });
            } else {
                setTimeout(poll_file_extraction, 2000);
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
