(function(exports) {
    "use strict";

    // Close the thank you window. TODO: Thank you windows are going away!
    $('#close-moz-pay-win').click(function(e) {
        e.preventDefault();
        _send('moz-pay-success');
    });

    $('#close-moz-error-win').click(function(e) {
        e.preventDefault();
        _send('moz-pay-failure');
    });

    function _send(msg) {
        // This is using '*' because we're not sure what the app domain is.
        // Maybe we can find that out.
        window.top.postMessage(msg, '*');
    }

})(typeof exports === 'undefined' ? (this.inapp_payments = {}) : exports);
