var z = {},
    // pretend to be underscore without the page weight
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

var preauth_window;

(function() {
    var win_top = window.top;
    if (win_top.opener) {
        win_top = win_top.opener;
    }
    $('.purchase').click(function(e) {
        $(this).addClass('purchasing').html($(this).data('purchasing-label'));
    });
    $('#setup-preauth').click(function(e) {
        e.preventDefault();
        if (preauth_window) {
            preauth_window.close();
        }
        preauth_window = window.open($(this).attr('href'));
        window.addEventListener('message', function(msg) {
            var result = msg.data;
            if (result == 'complete' || result == 'cancel') {
                preauth_window.close();
                window.location.reload();
            }
        }, false);
    });
    $('.close').click(function() {
        if ($('body').hasClass('success')) {
            win_top.postMessage('moz-pay-success', '*');
        } else {
            win_top.postMessage('moz-pay-cancel', '*');
        }
    });

})();
