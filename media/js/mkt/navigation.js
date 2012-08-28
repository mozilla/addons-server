
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
        } else {
            // handle the back and forward buttons.
            if (popped && stack[0].path === state.path) {
                stack.shift();
            } else {
                stack.unshift(state);
            }
        }

        setClass();

        setType();
    });

    var $body = $('body');

    var oldClass = '';
    function setClass() {
        // We so classy.
        var page = $('#page');
        var newClass = page.data('bodyclass');
        if (newClass) {
            $body.removeClass(oldClass).addClass(newClass);
            oldClass = newClass;
        }
    }

    function setType() {
        // We so type-y.
        var page = $('#page');
        var type = page.data('type');
        if (type) {
            $body.attr('data-page-type', type)
        }
    }

    function back() {
        stack.shift();
        $(window).trigger('loadfragment', stack[0].path);
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
