/*
JS included by any *remote* web app to enable in-app payments via Mozilla Marketplace

To use this script in your app, read the docs here:
https://developer.mozilla.org/en/Apps/In-app_payments

*/
(function(exports) {
"use strict";

exports.buy = function(signedRequest, onPaySuccess, onPayFailure) {
    if (typeof navigator.showPaymentScreen == 'undefined') {
        // Define our stub for prototyping.
        navigator.showPaymentScreen = navShowPaymentScreen;
    }
    navigator.showPaymentScreen(signedRequest, onPaySuccess, onPayFailure);
};




// -------------------------------------------------------------
// Delete all of this code. This is just a prototype for demos.
// -------------------------------------------------------------



var server, payWindow;

// Using jQuery for easy prototyping...
if (typeof $ === 'undefined') {
    console.log('This prototype currently requires jQuery');
}

setTimeout(function() {
    $('script').each(function(i, elem) {
        var src = $(elem).attr('src');
        if (src.search('mozmarket.js') != -1) {
            server = src.replace(/(https?:\/\/[^\/]+).*/g, '$1');
        }
    });
}, 1);


function navShowPaymentScreen(signedRequest, onPaySuccess, onPayFailure) {
    /*
        This will initially be implemented in the protected chrome of WebRT.
        This is a prototype implementation.
    */
    if (payWindow == null || payWindow.closed) {
        payWindow = window.open(server + '/payments/pay_start?req=' + signedRequest, 'moz-payment-screen',
                                'menubar=0,location=1,resizable=1,scrollbars=1,status=0,close=1,width=450,height=250,dialog=1');
    } else {
        payWindow.focus();
    }
}

})(typeof exports === 'undefined' ? (this.mozmarket = {}) : exports);
