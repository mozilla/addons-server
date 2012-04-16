var z = {},
    _ = {
    extend: function(obj, ext) {
        for (var p in ext) {
            obj[p] = ext[p];
        }
    }
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
            win_top.postMessage('mox-pay-cancel', '*');
        }
    });

})();
// (function(exports) {
//     "use strict";

//     // Close the thank you window. TODO: Thank you windows are going away!
//     $('#close-moz-pay-win').click(function(e) {
//         e.preventDefault();
//         _send('moz-pay-success');
//     });

//     $('#close-moz-error-win').click(function(e) {
//         e.preventDefault();
//         _send('moz-pay-failure');
//     });

//     function _send(msg) {
//         // This is using '*' because we're not sure what the app domain is.
//         // Maybe we can find that out.
//         window.top.postMessage(msg, '*');
//     }

// })(typeof exports === 'undefined' ? (this.inapp_payments = {}) : exports);
