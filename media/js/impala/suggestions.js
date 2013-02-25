$.fn.highlightTerm = function(val) {
    // If an item starts with `val`, wrap the matched text with boldness.
    val = val.replace(/[^\w\s]/gi, '');
    var pat = new RegExp(val, 'gi');
    this.each(function() {
        var $this = $(this),
            txt = $this.html(),
            matchedTxt = txt.replace(pat, '<b>$&</b>');
        if (txt != matchedTxt) {
            $this.html(matchedTxt);
        }
    });
};

/*
 * searchSuggestions
 * Grants search suggestions to an input of type text/search.
 * Required:
 * $results - a container for the search suggestions, typically UL.
 * processCallback - callback function that deals with the XHR call & populates
                   - the $results element.
 * Optional:
 * searchType - possible values are 'AMO', 'MKT'
*/
$.fn.searchSuggestions = function($results, processCallback, searchType) {
    var $self = this,
        $form = $self.closest('form');

    if (!$results.length) {
        return;
    }

    var cat = $results.attr('data-cat');

    if (searchType == 'AMO') {
        // Some base elements that we don't want to keep creating on the fly.
        var msg;
        if (cat == 'themes') {
            msg = gettext('Search themes for <b>{0}</b>');
        } else if (cat == 'apps') {
            msg = gettext('Search apps for <b>{0}</b>');
        } else {
            msg = gettext('Search add-ons for <b>{0}</b>');
        }
        var base = template('<div class="wrap">' +
                            '<p><a class="sel" href="#"><span>{msg}</span></a></p><ul></ul>' +
                            '</div>');
        $results.html(base({'msg': msg}));
    } else if (searchType == 'MKT') {
        $results.html('<div class="wrap"><ul></ul></div>');
    }

    // Control keys that shouldn't trigger new requests.
    var ignoreKeys = [
        z.keys.SHIFT, z.keys.CONTROL, z.keys.ALT, z.keys.PAUSE,
        z.keys.CAPS_LOCK, z.keys.ESCAPE, z.keys.ENTER,
        z.keys.PAGE_UP, z.keys.PAGE_DOWN,
        z.keys.LEFT, z.keys.UP, z.keys.RIGHT, z.keys.DOWN,
        z.keys.HOME, z.keys.END,
        z.keys.COMMAND, z.keys.WINDOWS_RIGHT, z.keys.COMMAND_RIGHT,
        z.keys.WINDOWS_LEFT_OPERA, z.keys.WINDOWS_RIGHT_OPERA, z.keys.APPLE
    ];

    var gestureKeys = [z.keys.ESCAPE, z.keys.UP, z.keys.DOWN];

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
        $results.removeClass('visible sel');
        if (searchType == 'MKT') {
            $('#site-header').removeClass('suggestions');
            if (z.capabilities.mobile && $('body.home').length === 0) {
                z.body.removeClass('show-search');
            }
        }
    }

    function gestureHandler(e) {
        // Bail if the results are hidden or if we have a non-gesture key
        // or if we have a alt/ctrl/meta/shift keybinding.
        if (!$results.hasClass('visible') ||
            $.inArray(e.which, gestureKeys) < 0 ||
            e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) {
            $results.trigger('keyIgnored');
            return;
        }
        e.preventDefault();
        if (e.which == z.keys.ESCAPE) {
            dismissHandler();
        } else if (e.which == z.keys.UP || e.which == z.keys.DOWN) {
            var $sel = $results.find('.sel'),
                $elems = $results.find('a'),
                i = $elems.index($sel.get(0));
            if ($sel.length && i >= 0) {
                if (e.which == z.keys.UP) {
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
        }
    }

    function inputHandler(e) {
        var val = escape_($self.val());
        if (val.length < 3) {
            $results.filter('.visible').removeClass('visible');
            return;
        }

        // Required data to send to the callback.
        var settings = {
            '$results': $results,
            '$form': $form,
            'searchTerm': val
        };

        // Optional data for callback.
        if (searchType == 'AMO' || searchType == 'MKT') {
            settings['category'] = cat;
        }

        if ((e.type === 'keyup' && typeof e.which === 'undefined') ||
            $.inArray(e.which, ignoreKeys) >= 0) {
            $results.trigger('inputIgnored');
        } else {
            // XHR call and populate suggestions.
            processCallback(settings);
        }
    }

    var pollVal = 0;

    if (z.capabilities.touch) {
        $self.focus(function() {
            // If we've already got a timer, clear it.
            if (pollVal !== 0) {
                clearInterval(pollVal);
            }
            pollVal = setInterval(function() {
                gestureHandler($self);
                inputHandler($self);
                return;
            }, 150);
        });
    } else {
        $self.keydown(gestureHandler).bind('keyup paste',
                                           _.throttle(inputHandler, 250));
    }

    function clearCurrentSuggestions(e) {
        clearInterval(pollVal);
        // Delay dismissal to allow for click events to happen on
        // results. If we call it immediately, results get hidden
        // before the click events can happen.
        _.delay(dismissHandler, 250);
        $self.trigger('dismissed');
    }

    $self.blur(clearCurrentSuggestions);
    $form.submit(function(e) {
        var $sel = $results.find('.sel');
        if ($sel.length && $sel.eq(0).attr('href') != '#') {
            e.stopPropagation();
            e.preventDefault();
            $self.val('');
            $sel[0].click();
        }
        $self.blur();
        clearCurrentSuggestions(e);
    });

    $results.delegate('li, p', 'hover', function() {
        $results.find('.sel').removeClass('sel');
        $results.addClass('sel');
        $(this).find('a').addClass('sel');
    }).delegate('a', 'click', function() {
        clearCurrentSuggestions();
        $self.val('');
    });

    $results.bind('highlight', function(e, val) {
        // If an item starts with `val`, wrap the matched text with boldness.
        $results.find('ul a span').highlightTerm(val);
        $results.addClass('visible');
        if (!$results.find('.sel').length) {
            pageUp();
        }
    });

    $results.bind('dismiss', clearCurrentSuggestions);

    $(document).keyup(function(e) {
        if (fieldFocused(e)) {
            return;
        }
        if (e.which == 83) {
            $self.focus();
        }
    });

    return this;
};
