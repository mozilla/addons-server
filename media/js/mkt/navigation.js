var nav = (function() {
    var stack = [
        {
            path: '/',
            type: 'root'
        }
    ];
    var param_whitelist = ['q', 'sort', 'cat'];

    function extract_nav_url(url) {
        // This function returns the URL that we should use for navigation.
        // It filters and orders the parameters to make sure that they pass
        // equality tests down the road.

        // If there's no URL params, return the original URL.
        if (url.indexOf('?') < 0) {
            return url;
        }

        var url_parts = url.split('?');
        // If there's nothing after the `?`, return the original URL.
        if (!url_parts[1]) {
            return url;
        }

        var used_params = _.pick(z.getVars(url_parts[1]), param_whitelist);
        // If there are no query params after we filter, just return the path.
        if (!_.keys(used_params).length) {  // If there are no elements in the object...
            return url_parts[0];  // ...just return the path.
        }

        var param_pairs = _.sortBy(_.pairs(used_params), function(x) {return x[0];});
        return url_parts[0] + '?' + _.map(
            param_pairs,
            function(pair) {
                if (typeof pair[1] === 'undefined')
                    return encodeURIComponent(pair[1]);
                else
                    return encodeURIComponent(pair[0]) + '=' +
                           encodeURIComponent(pair[1]);
            }
        ).join('&');
    }

    z.page.on('fragmentloaded', function(event, href, popped, state) {

        if (!state) return;

        // Clean the path's parameters.
        // /foo/bar?foo=bar&q=blah -> /foo/bar?q=blah
        state.path = extract_nav_url(state.path);

        // Truncate any closed navigational loops.
        for (var i=0; i<stack.length; i++) {
            if (stack[i].path === state.path) {
                stack = stack.slice(i+1);
                break;
            }
        }

        // Are we home? clear any history.
        if (state.type == 'root') {
            // Transition in the search for mobile after a scroll
            if (z.capabilities.mobile) {
                z.win.on('scroll', _.throttle(function(event) {
                    // Only add class on '.body.home' in case we've already
                    // navigated away by this point.
                    if (z.body.is('.home')) {
                        z.body.addClass('show-search');
                    }
                    $(this).unbind(event);
                }, 100));
            }
            stack = [state];
            // Also clear any search queries living in the search box.
            // Bug 790009
            $('#search-q').val('');
        } else {
            // handle the back and forward buttons.
            if (popped && stack[0].path === state.path) {
                stack.shift();
            } else {
                stack.unshift(state);
            }

            // Does the page have a parent? If so, handle the parent logic.
            if (z.context.parent) {
                var parent = _.indexOf(_.pluck(stack, 'path'), z.context.parent);

                if (parent > 1) {
                    // The parent is in the stack and it's not immediately
                    // behind the current page in the stack.
                    stack.splice(1, parent - 1);
                    console.log('Closing navigation loop to parent (1 to ' + (parent - 1) + ')');
                } else if (parent == -1) {
                    // The parent isn't in the stack. Splice it in just below
                    // where the value we just pushed in is.
                    stack.splice(1, 0, {path: z.context.parent});
                    console.log('Injecting parent into nav stack at 1');
                }
                console.log('New stack size: ' + stack.length);
            }
        }

        setClass();
        setTitle();
        setCSRF();
        setType();
    });

    var $body = $('body');

    var oldClass = '';
    function setClass() {
        // We so classy.
        var page = $('#page');
        var newClass = page.data('context').bodyclass;
        $body.removeClass(oldClass).addClass(newClass);
        oldClass = newClass;
    }

    function setType() {
        // We so type-y.
        var page = $('#page');
        var type = page.data('context').type;
        $body.attr('data-page-type', type || 'leaf');
    }

    function setTitle() {
        // Something something title joke.
        var $h1 = $('#site-header h1.page');
        var $wordMark = $h1.find('.wordmark');
        var title = $('#page').data('context').headertitle || '';
        if ($wordMark.length) {
            $wordMark.text(title);
        } else {
            $h1.text(title);
        }
    }

    function setCSRF() {
        // We CSRFing USA.
        var csrf = $('#page').data('context').csrf;
        if (csrf) {
            $('meta[name=csrf]').val(csrf);
        }
    }

    function back() {
        // Something something back joke.
        if (stack.length > 1) {
            stack.shift();
            z.doc.trigger('loadfragment', stack[0].path);
        } else {
            console.log('attempted nav.back at root!');
        }
    }

    z.doc.on('click', '.back:not(.dismiss)', _pd(back));

    return {
        stack: function() {
            return stack;
        },
        back: back,
        oldClass: function() {
            return oldClass;
        }
    };

})();
