function _pd(func) {
    return function(e) {
        e.preventDefault();
        func.apply(this, arguments);
    };
}


function fieldFocused(e) {
    var tags = /input|keygen|meter|option|output|progress|select|textarea/i;
    return tags.test(e.target.nodeName);
}


function postUnsaved(data) {
    $('input[name="unsaved_data"]').val(JSON.stringify(data));
}


function loadUnsaved() {
    return JSON.parse($('input[name="unsaved_data"]').val() || '{}');
}


var escape_ = function(s) {
    if (s === undefined) {
        return;
    }
    return s.replace(/&/g, '&amp;').replace(/>/g, '&gt;').replace(/</g, '&lt;')
            .replace(/'/g, '&#39;').replace(/"/g, '&#34;');
};


// Sexy setTimeout. wait(1000).then(doSomething);
function wait(ms) {
    var $d = $.Deferred();
    setTimeout(function() {
        $d.resolve();
    }, ms);
    return $d.promise();
}


_.extend(String.prototype, {
    trim: function(str) {
        // Trim leading and trailing whitespace (like lstrip + rstrip).
        return this.replace(/^\s*/, '').replace(/\s*$/, '');
    },
    strip: function(str) {
        // Strip all whitespace.
        return this.replace(/\s/g, '');
    }
});

function makeOrGetOverlay(opts) {
    var classes = 'overlay',
        id = opts;
    if (_.isObject(opts)) {
        if ('class' in opts) {
            classes += ' ' + opts.class;
        }
        id = opts.id;
    }
    var el = $('#' + id);
    if (!el.length) {
        el = $('<div class="' + classes + '" id="' + id +'">');
        $('body').append(el);
    }
    return el;
}

function getTemplate($el) {
    // If the element exists, return the template.
    if ($el.length) {
        return template($el.html());
    }
    // Otherwise, return undefined.
}

// Initializes character counters for textareas.
function initCharCount(parent) {
    /*
    parent - An optional parameter that allows the effects of this function to
             be limited to a single node rather than the whole document.
    */
    var countChars = function(el, cc) {
        var $el = $(el),
            val = $el.val(),
            max = parseInt(cc.attr('data-maxlength'), 10),
            left = max - val.length,
            cc_parent = cc.parent();
        // L10n: {0} is the number of characters left.
        cc.html(format(ngettext('{0} character left.',
                                '{0} characters left.', left), [left]))
          .toggleClass('error', left < 0);
        if(left >= 0 && cc_parent.hasClass('error')) {
            cc_parent.removeClass('error');
        }
    };
    $('.char-count', parent).each(function() {
        var $this = $(this)
        var $cc = $(this),
            $form = $(this).closest('form'),
            $el;
        if ($cc.attr('data-for-startswith') !== undefined) {
            $el = $('textarea[id^="' + $cc.attr('data-for-startswith') + '"]:visible', $form);
        } else {
            $el = $('textarea#' + $cc.attr('data-for'), $form);
        }
        $el.bind('keyup blur', _.throttle(function() {
            countChars(this, $cc);
        }, 250)).trigger('blur');
    });
}


function successNotification(msg) {
    var success = $('.success h2');
    if (success.length) {
        success.text(msg);
    } else {
        $('#page').prepend($('<section class="full notification-box">' +
                             '<div class="success"><h2>' + msg +
                             '</h2></div></section>'));
    }
}


$(document).ajaxSuccess(function(event, xhr, ajaxSettings) {
    z.win.trigger('resize'); // Redraw what needs to be redrawn.
}).on('click', 'a.external, a[rel=external]', function() {
    // If we're inside the Marketplace app, open external links in the Browser.
    if (z.capabilities.chromeless) {
        $(this).attr('target', '_blank');
    }
});
