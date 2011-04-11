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
                        html.push(format('<div><div class="number"><a href="#L{0}" name="L{0}">{0}</a>' +
                                         '</div><div class="code add">{1}</div></div>', k, lines[t]));
                        k++;
                        break;
                    case DIFF_DELETE:
                        html.push(format('<div><div class="number"></div>' +
                                         '<div class="code delete">{0}</div></div>', lines[t]));
                        break;
                    case DIFF_EQUAL:
                        html.push(format('<div><div class="number"><a href="#L{0}" name="L{0}">{0}</a>' +
                                         '</div><div class="code">{1}</div></div>', k, lines[t]));
                        k++;
                        break;
                }
            }
        }
        return html.join('\n');
    };
}

function bind_viewer() {
    function Viewer() {
        this.$tree = $('#files ul');
        this.compute = function() {
            var node = $('#content');
            if (node.length) {
                var splitted = node.text().split('\n'),
                    length = splitted.length,
                    html = [];
                if (splitted.splice(length-1, length) == '') {
                    length = length - 1;
                }
                for (var k = 0; k < splitted.length; k++) {
                    var text = splitted[k].replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                    html.push(format('<div><div class="number"><a href="#L{0}" name="L{0}">{0}</a></div>' +
                                     '<div class="code">{1}</div></div>', k+1, text));
                }
                node.html(html.join('\n'));
            }

            if ($('#diff').length) {
                var dmp = new diff_match_patch();
                var diff = dmp.diff_main($('#file-one').text(), $('#file-two').text());
                $('#diff').html(dmp.diff_prettyHtml(diff));
            }

            if (window.location.hash) {
                window.location = window.location;
            }
            this.$tree.show();
        };
        this.show_leaf = function(names) {
            /* Exposes the leaves for a given set of nodes. */
            this.$tree.find('li').each(function() {
                var $this = $(this),
                    parent = $this.attr('data-parent'),
                    shrt = $this.attr('data-short'),
                    a = $this.find('a');

                if (parent && (names.indexOf(parent) > -1) &&
                    $this.hasClass('hidden')) {
                        $this.removeClass('hidden').show();
                }

                else if (names.length === 1 &&
                         (shrt.length > names[0].length) &&
                         (shrt.indexOf(names[0]) === 0)) {
                    $this.addClass('hidden').hide();
                    if (a.hasClass('open')) {
                        a.removeClass('open').addClass('closed');
                    }
                }

                if (names.indexOf($this.attr('data-short')) > -1) {
                    if (a.hasClass('closed')) {
                        a.removeClass('closed').addClass('open');
                    }
                }
            });
        };
        this.selected = function($link) {
            /* Updates the tree, showing the leaves relevant to node */
            var $curr = $link.closest('li'),
                leaf = $curr.attr('data-parent').split('/'),
                names = [];
            $curr.removeClass('hidden').show();
            if (leaf.length && (leaf[0])) {
                for (var k = 0; k <= leaf.length; k += 1) {
                    names.push(leaf.slice(0, k).join('/'));
                }
                this.show_leaf(names);
            }
        };
        this.load = function($link) {
            /* Accepts a jQuery wrapped node, which is part of the tree.
               Hides content, shows spinner, gets the content and then
               shows it all. */
            var self = this,
                $thinking = $('#thinking'),
                $wrapper = $('#content-wrapper');
            $wrapper.hide();
            $thinking.removeClass('hidden').show();
            if (history.pushState !== undefined) {
                history.pushState({ path: $link.text() }, '', $link.attr('href'));
            }
            $('#content-wrapper').load($link.attr('href') + ' #content-wrapper', function() {
                $(this).children().unwrap();
                self.compute();
                $thinking.hide();
                $wrapper.slideDown();
            });
        };
        this.select = function($link) {
            /* Given a node, alters the tree and then loads the content. */
            this.$tree.find('a.selected').each(function() {
                $(this).removeClass('selected');
            });
            $link.addClass('selected');
            this.selected($link);
            this.load($link);
        };
        this.get_selected = function() {
            return this.$tree.find('a.selected');
        };
    }

    var viewer = new Viewer();

    viewer.$tree.find('.directory').click(_pd(function() {
        viewer.show_leaf([$(this).closest('li').attr('data-short')]);
    }));

    $('#files-prev').click(_pd(function() {
        var $curr = viewer.get_selected().closest('li'),
            choices = $curr.prevUntil('ul').find('a.file');
        if (choices.length) { viewer.select($(choices[0])); }
    }));

    $('#files-next').click(_pd(function() {
        var $curr = viewer.get_selected().closest('li'),
            choices = $curr.nextUntil('ul').find('a.file');
        if (choices.length) { viewer.select($(choices[0])); }
    }));

    $('#files-wrap').click(_pd(function() {
        $('pre').addClass('wrapped');
        $('#files-wrap').hide();
        $('#files-unwrap').removeClass('hidden').show();
    }));

    $('#files-unwrap').click(_pd(function() {
        $('pre').removeClass('wrapped');
        $('#files-wrap').removeClass('hidden').show();
        $('#files-unwrap').hide();
    }));

    $('#files-expand-all').click(_pd(function() {
        viewer.$tree.find('li.hidden').removeClass('hidden').show();
        viewer.$tree.find('a.directory').removeClass('closed').addClass('open');
    }));

    viewer.$tree.find('.file').click(_pd(function() {
        viewer.select($(this));
        $('#files-unwrap').removeClass('hidden').show();
        $('#files-wrap').hide();
    }));

    $(document).bind('keyup', _pd(function(e) {
        if (e.keyCode === 75) {
            $('#files-next').trigger('click');
        } else if (e.keyCode === 74) {
            $('#files-prev').trigger('click');
        }
    }));

    return viewer;
}

$(document).ready(function() {
    var viewer = null;

    function poll_file_extraction() {
        $.getJSON($('#extracting').attr('data-url'), function(json) {
            if (json && json.status) {
                $('#file-viewer').load(window.location.pathname + ' #file-viewer', function() {
                    viewer = bind_viewer();
                    viewer.selected(viewer.$tree.find('a.selected'));
                    viewer.compute();
                });
            } else {
                setTimeout(poll_file_extraction, 2000);
            }
        });
    }

    if ($('#extracting').length) {
        poll_file_extraction();
    } else if ($('#file-viewer').length) {
        viewer = bind_viewer();
        viewer.selected(viewer.$tree.find('a.selected'));
        viewer.compute();
    }
});
