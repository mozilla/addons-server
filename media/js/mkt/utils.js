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


$('html').ajaxSuccess(function(event, xhr, ajaxSettings) {
    $(window).trigger('resize'); // Redraw what needs to be redrawn.
});


// If any field changes, submit the form.
$('form.go').change(function() {
    this.submit();
});
