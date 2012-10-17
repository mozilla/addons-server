
var nav = (function() {
    var stack = [
        {
            path: '/',
            type: 'root'
        }
    ];

    z.page.on('fragmentloaded', function(event, href, popped, state) {

        // Truncate any closed navigational loops.
        for (var i=0; i<stack.length; i++) {
            if (stack[i].path === state.path) {
                stack = stack.slice(i+1);
                break;
            }
        }

        // Are we home? clear any history.
        if (state.type == 'root') {
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
        }

        setClass();
        setTitle();
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
        var $h1 = $('#site-header h1');
        var title = $('#page').data('context').headertitle || '';
        $h1.text(title);
    }

    function back() {
        if (stack.length > 1) {
            stack.shift();
            $(window).trigger('loadfragment', stack[0].path);
        } else {
            console.log('attempted nav.back at root!');
        }
    }

    $('#nav-back').on('click', _pd(back));

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
