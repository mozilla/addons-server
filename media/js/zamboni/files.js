if (typeof diff_match_patch !== 'undefined') {
    diff_match_patch.prototype.diff_prettyHtml = function(diffs) {
        /* An override of prettyHthml from diff_match_patch. This
           one will not put any style attrs in the ins or del. It will
           also as side effect write an array of line numbers, ignoring
           deletions */
        var html = [],
            pattern_amp = /&/g,
            pattern_lt = /</g,
            pattern_gt = />/g,
            pattern_para = /\n/g;

        this.line_numbers = [];
        var k = 1,
            i = 0;
        for (var x = 0; x < diffs.length; x++) {
            var op = diffs[x][0];    // Operation (insert, delete, equal)
            var data = diffs[x][1];  // Text of change.
            var text = data.replace(pattern_amp, '&amp;').replace(pattern_lt, '&lt;')
                           .replace(pattern_gt, '&gt;').replace(pattern_para, '\n');
            /* As as side effect, append on to the line_numbers a list
              of numbers, with false for empty ones. So that <del> don't
              have a line number. To get the numbers balanced, we need
              to strip a starting or ending "" in the text */
            var lines = text.split('\n');
            if (lines[lines.length-1] === '') {
                lines.pop();
            }
            if (lines[0] === '') {
                lines.splice(0, 1);
            }
            for (var t = 0; t < lines.length; t++) {
                if (op === DIFF_DELETE) {
                    this.line_numbers.push(false);
                } else {
                    this.line_numbers.push(k++);
                }

                switch (op) {
                    case DIFF_INSERT:
                        html.push('<ins>+ ' + lines[t] + '</ins>');
                        break;
                    case DIFF_DELETE:
                        html.push('<del>- ' + lines[t] + '</del>');
                        break;
                    case DIFF_EQUAL:
                        html.push('<div> ' + lines[t] + '</div>');
                    break;
                }
                if (op !== DIFF_DELETE) {
                    i += data.length;
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
            /* Counts the line numbers.
              If we've got diffs, computes the diffs and the line numbers.
              The line number computation is so that we don't show line numbers
              on - lines. */
            if ($('#content').length) {
                var text = $('#content').text(),
                    length = text.split('\n').length,
                    num = [];
                for (var k = 1; k < Math.max(1, length); k++) {
                    num.push(k);
                }
                if (text.slice(text.length-1, text.length) !== '\n') {
                    num.push(num.slice(num.length-1, num.length) + 1);}
                this.add_numbers(num);
            }

            if ($('#diff').length) {
                var dmp = new diff_match_patch();
                var diff = dmp.diff_main($('#file-one').text(), $('#file-two').text());
                $('#diff').html(dmp.diff_prettyHtml(diff));
                this.add_numbers(dmp.line_numbers);
            }
            this.$tree.show();
        };
        this.add_numbers = function(num) {
            /* Adds the line numbers into the page after counting. */
            var text = [];
            for (var k = 0; k < num.length; k++) {
                text.push(num[k] === false ? '<br/>' : format('<a href="#L{0}" name="L{0}">{0}</a><br/>', num[k]));
            }
            // Because the line numbers are generated dynamically,
            // it won't go to the anchor.
            if (window.location.hash) {
                window.location = window.location;
            }
            $('#numbers').html(text.join('\n'));
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
                $wrapper = $('#wrapper');
            $wrapper.hide();
            $thinking.removeClass('hidden').show();
            history.pushState({ path: $link.text() }, '', $link.attr('href'));
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

    $('#files-expand-all').click(_pd(function() {
        viewer.$tree.find('li.hidden').removeClass('hidden').show();
        viewer.$tree.find('a.directory').removeClass('closed').addClass('open');
    }));

    $('#files li a').click(_pd(function() {
        viewer.select($(this));
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
