$.fn.highlightTerm = function(val) {
    // If an item starts with `val`, wrap the matched text with boldness.
    val = val.replace(/[^\w\s]/gi, '');
    var pat = new RegExp(val, 'gi');
    this.each(function() {
        var $this = $(this),
            txt = escape_($this.html()),
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
 * siteSearch - boolean of whether this is a site-search suggestions box which
              - deals with multiple types of search results (apps/personas/etc)
*/
$.fn.searchSuggestions = function($results, processCallback, siteSearch) {
    var $self = this,
        $form = $self.closest('form');

    if (!$results.length) {
        return;
    }

    if (siteSearch) {
        // Some base elements that we don't want to keep creating on the fly.
        var cat = $results.attr('data-cat'),
            msg;
        if (cat == 'personas') {
            msg = gettext('Search personas for <b>{0}</b>');
        } else if (cat == 'apps') {
            msg = gettext('Search apps for <b>{0}</b>');
        } else {
            msg = gettext('Search add-ons for <b>{0}</b>');
        }
        var base = template('<div class="wrap">' +
                            '<p><a class="sel" href="#"><span>{msg}</span></a></p><ul></ul>' +
                            '</div>');
        $results.html(base({'msg': msg}));
    }

    // Control keys that shouldn't trigger new requests.
    var ignoreKeys = [
        z.keys.SHIFT, z.keys.CONTROL, z.keys.ALT, z.keys.PAUSE,
        z.keys.CAPS_LOCK, z.keys.ESCAPE, z.keys.ENTER,
        z.keys.PAGE_UP, z.keys.PAGE_DOWN,
        z.keys.LEFT, z.keys.UP, z.keys.RIGHT, z.keys.DOWN,
        z.keys.HOME, z.keys.END,
        z.keys.COMMAND, z.keys.WINDOWS_RIGHT, z.keys.COMMAND_RIGHT,
        z.keys.WINDOWS_LEFT_OPERA, z.keys.WINDOWS_RIGHT_OPERA, z.keys.APPLE,
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
        if ($results.hasClass('locked')) {
            return;
        }
        $results.removeClass('visible sel');
        $results.find('.sel').removeClass('sel');
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
            'searchTerm': val,
        };

        // Optional data for callback.
        if (siteSearch) {
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

    var pollVal;

    if (z.capabilities.touch) {
        $self.focus(function() {
            pollVal = setInterval(function() {
                gestureHandler($self);
                inputHandler($self);
                return;
            }, 250);
        });
    }

    $self.keydown(gestureHandler)
         .bind('keyup paste', _.throttle(inputHandler, 250))
         .blur(function() {
           clearInterval(pollVal);
           _.delay(dismissHandler, 250);
       });

    $results.delegate('li, p', 'hover', function() {
        $results.find('.sel').removeClass('sel');
        $results.addClass('sel');
        $(this).find('a').addClass('sel');
    }).delegate('a', 'click', _pd(function() {
        $results.addClass('locked');
        $form.submit();
    }));

    $results.bind('highlight', function(e, val) {
        // If an item starts with `val`, wrap the matched text with boldness.
        $results.find('ul a span').highlightTerm(val);
        $results.addClass('visible');
        if (!$results.find('.sel').length) {
            pageUp();
        }
    });

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
        if (e.which == 83) {
            $self.focus();
        }
    });

    return this;
};
