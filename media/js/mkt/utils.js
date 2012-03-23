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


// CSRF Tokens
// Hijack the AJAX requests, and insert a CSRF token as a header.

$('html').ajaxSend(function(event, xhr, ajaxSettings) {
    var csrf, $meta;
    // Block anything that starts with 'http:', 'https:', '://' or '//'.
    if (!/^((https?:)|:?[/]{2})/.test(ajaxSettings.url)) {
        // Only send the token to relative URLs i.e. locally.
        $meta = $('meta[name=csrf]');
        if (!z.anonymous && $meta.length) {
            csrf = $meta.attr('content');
        } else {
            csrf = $("input[name='csrfmiddlewaretoken']").val();
        }
        if (csrf) {
            xhr.setRequestHeader('X-CSRFToken', csrf);
        }
    }
}).ajaxSuccess(function(event, xhr, ajaxSettings) {
    $(window).trigger('resize'); // Redraw what needs to be redrawn.
});
