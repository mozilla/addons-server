var z = {},
    _ = {
    extend: function(obj, ext) {
        for (var p in ext) {
            obj[p] = ext[p];
        }
    }
};

var escape_ = function(s) {
    if (s === undefined) {
        return;
    }
    return s.replace(/&/g, '&amp;').replace(/>/g, '&gt;').replace(/</g, '&lt;')
            .replace(/'/g, '&#39;').replace(/"/g, '&#34;');
};

(function() {
    var win_top = window.top;
    if (win_top.opener) {
        win_top = win_top.opener;
    }
    $('.close').click(function() {
        if ($('body').hasClass('success')) {
            win_top.postMessage('moz-pay-success', '*');
        } else {
            win_top.postMessage('moz-pay-cancel', '*');
        }
    });

})();
