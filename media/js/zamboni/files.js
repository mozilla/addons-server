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

function Tree() {
    this.$node = $('.files ul li');
    this.show_leaf = function(names) {
        this.$node.each(function() {
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
                } else {
                    a.removeClass('open').addClass('closed');
                }
            }
        });
    };
    this.selected = function() {
        var self = this;
        $('#file-viewer .selected').each(function() {
            var $curr = $(this).closest('li'),
                leaf = $curr.attr('data-parent').split('/');
                names = [];
            $curr.removeClass('hidden').show();
            if (leaf.length && (leaf[0])) {
                for (var k = 0; k <= leaf.length; k += 1) {
                    names.push(leaf.slice(0, k).join('/'));
                }
                self.show_leaf(names);
            }
        });
    };
    this.select = function($link) {
        this.$node.find('a.selected').each(function() {
            $(this).removeClass('selected');
        });
        $link.addClass('selected');
        this.selected();
    };
}

function Numbers() {
    this.count = function() {
        this.$node = $('.numbers');
        if ($('#content').length) {
            var length = $('#content').text().split('\n').length,
                num = [];
            for (var k = 1; k < Math.max(2, length); k++) {
                num.push(k);
            }
            this.add(num);
        }

        if ($('#diff').length) {
            var dmp = new diff_match_patch();
            var diff = dmp.diff_main($('#file-one').text(),
                                     $('#file-two').text());
            $('#diff').html(dmp.diff_prettyHtml(diff));
            this.add(dmp.line_numbers);
        }
    };
    this.add = function(num) {
        this.$node = $('.numbers');
        this.$node.html('');
        for (var k = 0; k < num.length; k++) {
            if (num[k] === false) {
                this.$node.append('<br/>');
            } else {
                this.$node.append('<a href="#L' + num[k] + '" name="L' +
                                  num[k] + '">' + num[k] + '</a><br/>');
            }
        }
        // Because the line numbers are generated dynamically,
        // it won't go to the anchor.
        if (window.location.hash) {
            window.location = window.location;
        }
    };
}

$(document).ready(function() {
    function poll_file_extraction() {
        $.getJSON($('#waiting').attr('data-url'), function(json) {
            if (json && json.status) {
                $('#file-viewer').load(window.location.pathname + ' #file-viewer');
            } else {
                setTimeout(poll_file_extraction, 2000);
            }
        });
    }

    var tree = new Tree();
    tree.selected();
    var numbers = new Numbers();
    numbers.count();

    if ($('#waiting').length) {
        poll_file_extraction();
    }

    if ($('#file-viewer').length) {
        $('#file-viewer .directory').click(function() {
            tree.show_leaf([$(this).closest('li').attr('data-short')]);
            return false;
        });

        $('.files li a').click(function() {
            var $link = $(this);
            history.pushState({ path: this.text }, '', this.href);
            $('.content-wrapper').load(this.href + ' .content-wrapper', function() {
                numbers.count();
                tree.select($link);
            });
            return false;
        });

        $(window).bind('popstate', function() {
            $('.content').load(location.pathname + ' .content-wrapper', function() {
                numbers.count();
            });
        });

        $('#files-prev').click(function() {
            var $curr = $('#file-viewer a.selected').closest('li'),
                choices = $curr.prevUntil('ul').find('a.file');
            if (choices.length) {
                $(choices[0]).trigger('click');
            }
            return false;
        });

        $('#files-next').click(function() {
            var $curr = $('#file-viewer a.selected').closest('li'),
                choices = $curr.nextUntil('ul').find('a.file');
            if (choices.length) {
                $(choices[0]).trigger('click');
            }
            return false;
        });

        $('#files-expand-all').click(function() {
            $('#file-viewer .hidden').removeClass('hidden').show();
            $('#file-viewer .directory').removeClass('closed').addClass('open');
            return false;
        });

        $(document).bind('keyup', function(e) {
            if (e.keyCode === 75) {
                $('#files-next').trigger('click');
            } else if (e.keyCode === 74) {
                $('#files-prev').trigger('click');
            }
            return false;
        });
    }
});
