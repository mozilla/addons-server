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


var escape_ = function(s) {
    if (s === undefined) {
        return;
    }
    return s.replace(/&/g, '&amp;').replace(/>/g, '&gt;').replace(/</g, '&lt;')
            .replace(/'/g, '&#39;').replace(/"/g, '&#34;');
};


String.prototype.startsWith = function(str) {
    return this.slice(0, str.length) == str;
};
String.prototype.endsWith = function(str) {
    return this.slice(-str.length) == str;
};
String.prototype.trim = function(str) {
    // Trim leading and trailing whitespace (like lstrip + rstrip).
    return this.replace(/^\s*/, '').replace(/\s*$/, '');
};
String.prototype.strip = function(str) {
    // Strip all whitespace.
    return this.replace(/\s/g, '');
};


// Sample usage:
// ['/en-US/apps/', '/ja/search/', '/fr/contact/'].startsWith('/en-US/')
Array.prototype.startsWith = function(str) {
    for (var i = 0; i < this.length; i++) {
        if (str.startsWith(this[i])) {
            return true;
        }
    }
    return false;
};


// .exists()
// This returns true if length > 0.
$.fn.exists = function(callback, args) {
    var $this = $(this),
        len = $this.length;
    if (len && callback) {
        callback.apply(null, args);
    }
    return !!len;
};

function makeOrGetOverlay(id) {
    var el = document.getElementById(id);
    if (!el) {
        el = $('<div class="overlay">', {
            id: id
        });
        $('body').append(el);
    }
    return $(el);
}

// Initializes character counters for textareas.
function initCharCount() {
    var countChars = function(el, cc) {
        var $el = $(el),
            val = $el.val(),
            max = parseInt(cc.attr('data-maxlength'), 10),
            left = max - val.length;
        // L10n: {0} is the number of characters left.
        cc.html(format(ngettext('<b>{0}</b> character left.',
                                '<b>{0}</b> characters left.', left), [left]))
          .toggleClass('error', left < 0);
    };
    $('.char-count').each(function() {
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

function addParamToURL(param, _url){
    _url += (_url.split('?')[1] ? '&':'?') + param;
    return _url;
}

$('html').ajaxSuccess(function(event, xhr, ajaxSettings) {
    $(window).trigger('resize'); // Redraw what needs to be redrawn.
});


// If any field changes, submit the form.
$('form.go').change(function() {
    this.submit();
});
