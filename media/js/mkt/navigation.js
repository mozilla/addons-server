
var nav = (function() {
    var stack = [
        {
            path: '/',
            type: 'root'
        }
    ];
    // Ask potch.
    var path_a = document.createElement('a');

    z.page.on('fragmentloaded', function(event, href, popped, state) {

        // Truncate any closed navigational loops.
        for (var i=0; i<stack.length; i++) {
            if (stack[i].path === state.path) {
                stack = stack.slice(i+1);
                break;
            }
        }
        // <ask potch>
        path_a.href = state.path;
        state.path = path_a.pathname;
        // </ask>

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
