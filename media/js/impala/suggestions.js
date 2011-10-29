$(document).ready(function() {
    $('#search #search-q').searchSuggestions($('#site-search-suggestions'));
});


$.fn.highlightTerm = function(val) {
    // If an item starts with `val`, wrap the matched text with boldness.
    val = val.replace(/[^\w\s]/gi, '');
    var pat = new RegExp(val, 'gi');
    this.each(function() {
        var $this = $(this),
            txt = $this.text(),
            matchedTxt = txt.replace(pat, '<b>$&</b>');
        if (txt != matchedTxt) {
            $this.html(matchedTxt);
        }
    });
};


$.fn.searchSuggestions = function(results) {
    var $self = this,
        $form = $self.closest('form'),
        $results = results;

    if (!$results.length) {
        return;
    }

    // Some base elements that we don't want to keep creating on the fly.
    var cat = $form.find('input[name=cat]').val(),
        msg;
    if (cat == 'personas') {
        msg = gettext('Search personas for <b>{0}</b>');
    } else if (cat == 'apps') {
        msg = gettext('Search apps for <b>{0}</b>');
    } else {
        msg = gettext('Search add-ons for <b>{0}</b>');
    }
    var base = template('<div class="wrap">' +
                        '<p><a class="sel" href="#">{msg}</a></p><ul></ul>' +
                        '</div>');
    $results.html(base({'msg': msg}));

    // Control keys that shouldn't trigger new requests.
    var ignoreKeys = [
        $.ui.keyCode.SHIFT, $.ui.keyCode.CONTROL, $.ui.keyCode.ALT,
        19,  // pause
        $.ui.keyCode.CAPS_LOCK, $.ui.keyCode.ESCAPE, $.ui.keyCode.ENTER,
        $.ui.keyCode.PAGE_UP, $.ui.keyCode.PAGE_DOWN,
        $.ui.keyCode.LEFT, $.ui.keyCode.UP,
        $.ui.keyCode.RIGHT, $.ui.keyCode.DOWN,
        $.ui.keyCode.HOME, $.ui.keyCode.END,
        $.ui.keyCode.COMMAND,
        92,  // right windows key
        $.ui.keyCode.COMMAND_RIGHT,
        219,  // left windows key (Opera)
        220,  // right windows key (Opera)
        224   // apple key
    ];

    var gestureKeys = [
        $.ui.keyCode.ESCAPE, $.ui.keyCode.UP, $.ui.keyCode.DOWN,
        $.ui.keyCode.PAGE_UP, $.ui.keyCode.PAGE_DOWN,
        $.ui.keyCode.HOME, $.ui.keyCode.END
    ];

    function pageUp() {
        // Select the first element.
        $results.find('.sel').removeClass('sel');
        $results.removeClass('sel');
        $results.find('a:first').addClass('sel');
    }
    function pageDown() {
        // Select the last element.
        $results.find('.sel').removeClass('sel');
        $results.removeClass('sel');
        $results.find('a:last').addClass('sel');
    }

    function dismissHandler() {
        if ($results.hasClass('locked')) {
            return;
        }
        $results.removeClass('visible sel');
        $results.find('.sel').removeClass('sel');
    }

    function gestureHandler(e) {
        if (!$results.hasClass('visible')) {
            return;
        }
        if ($.inArray(e.which, gestureKeys) >= 0) {
            e.preventDefault();
        }
        if (e.which == $.ui.keyCode.ESCAPE) {
            dismissHandler();
        }
        if (e.which == $.ui.keyCode.UP || e.which == $.ui.keyCode.DOWN) {
            var $sel = $results.find('.sel'),
                $elems = $results.find('a'),
                i = $elems.index($sel.get(0));
            if ($sel.length && i >= 0) {
                if (e.which == $.ui.keyCode.UP) {
                    // Clamp the value so it goes to the previous row
                    // but never goes beyond the first row.
                    i = Math.max(0, i - 1);
                } else {
                    // Clamp the value so it goes to the next row
                    // but never goes beyond the last row.
                    i = Math.min(i + 1, $elems.length - 1);
                }
            } else {
                i = 0;
            }
            $sel.removeClass('sel');
            $elems.eq(i).addClass('sel');
            $results.addClass('sel').trigger('selectedRowUpdate', [i]);
        } else if (e.which == $.ui.keyCode.PAGE_UP ||
                   e.which == $.ui.keyCode.HOME) {
            pageUp();
            $results.addClass('sel').trigger('selectedRowUpdate', [0]);
        } else if (e.which == $.ui.keyCode.PAGE_DOWN ||
                   e.which == $.ui.keyCode.END) {
            pageDown();
            $results.addClass('sel').trigger('selectedRowUpdate',
                                             [$results.find('a').length - 1]);
        }
    }

    function inputHandler(e) {
        var val = escape_($self.val());
        if (val.length < 3) {
            $results.filter('.visible').removeClass('visible');
            return;
        }

        if (e.which === undefined || $.inArray(e.which, ignoreKeys) >= 0) {
            $results.trigger('inputIgnored');
        } else {
            // Update the 'Search add-ons for <b>"{addon}"</b>' text.
            $results.find('p b').html(format('"{0}"', [val]));

            var li_item = template(
                '<li><a href="{url}" {icon} {cls}>{name}</a></li>'
            );

            $.ajaxCache({
                url: $results.attr('data-src'),
                data: $form.serialize(),
                newItems: function(formdata, items) {
                    var eventName;
                    if (items !== undefined) {
                        var ul = '';
                        $.each(items, function(i, item) {
                            var d = {
                                url: escape_(item.url) || '#',
                                icon: '',
                                cls: ''
                            };
                            if (item.icon) {
                                d.icon = format(
                                    'style="background-image:url({0})"',
                                    escape_(item.icon));
                            }
                            if (item.cls) {
                                d.cls = format('class="{0}"',
                                               escape_(item.cls));
                            }
                            if (item.name) {
                                d.name = escape_(item.name);
                                // Append the item only if it has a name.
                                ul += li_item(d);
                            }
                        });
                        $results.find('ul').html(ul);
                    }
                    highlight(val);
                    $results.trigger('resultsUpdated', [items]);
                }
            });
        }
    }

    $self.blur(function() { _.delay(dismissHandler, 250); })
         .keydown(gestureHandler)
         .bind('keyup paste', _.throttle(inputHandler, 250));

    $results.delegate('li, p', 'hover', function() {
        $results.find('.sel').removeClass('sel');
        $results.addClass('sel');
        $(this).find('a').addClass('sel');
    }).delegate('a', 'click', _pd(function() {
        $results.addClass('locked');
        $form.submit();
    }));

    $form.submit(function(e) {
        var $sel = $results.find('.sel');
        if ($sel.length && $sel.eq(0).attr('href') != '#') {
            e.stopPropagation();
            e.preventDefault();
            window.location = $sel.get(0).href;
        }
        $results.removeClass('locked');
        dismissHandler();
    });

    $(document).keyup(function(e) {
        if (fieldFocused(e)) {
            return;
        }
        if (e.which == 16 || e.which == 83) {
            $self.focus();
        }
    });

    function highlight(val) {
        // If an item starts with `val`, wrap the matched text with boldness.
        $results.find('ul a').highlightTerm(val);
        $results.addClass('visible');
        if (!$results.find('.sel').length) {
            pageUp();
        }
    }

    return this;
};
