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
        navigator.showPaymentScreen = showPaymentScreen;
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


function showPaymentScreen(signedRequest, onPaySuccess, onPayFailure) {
    // check cookie for marketplace session?
    // _popup_showPaymentScreen(signedRequest, onPaySuccess, onPayFailure);
    _overlay_showPaymentScreen(signedRequest, onPaySuccess, onPayFailure);
}

function _overlay_showPaymentScreen(signedRequest, onPaySuccess, onPayFailure) {
    var $overlay = $('#moz-payment-overlay'),
        width = 450,
        left = ($(window).width() - width) / 2,
        top = $(window).scrollTop() + 26; // distance from top of the window;
    if ($overlay.length) {
        // If an app defined their own then remove it.
        // TODO: more click jacking protection :/
        $overlay.remove();
    }
    $overlay = $('<iframe></iframe>', {'id': 'moz-payment-overlay',
                                       'type': 'text/html',
                                       'src': server + '/inapp-pay/pay_start?req=' + signedRequest});
    $overlay.css({'position': 'absolute',
                  'top': top + 'px',
                  'left': left + 'px',
                  'width': width + 'px',
                  'height': '250px',
                  'background': '#fff',
                  'z-index': '2001',
                  'border': '3px solid #2e5186',
                  '-webkit-border-radius': '8px',
                  '-moz-border-radius': '8px',
                  'border-radius': '8px',
                  'box-shadow': '0 1px 3px rgba(0, 0, 0, 0.35)',
                  '-moz-box-shadow': '0 1px 3px rgba(0, 0, 0, 0.35)',
                  '-webkit-box-shadow': '0 1px 3px rgba(0, 0, 0, 0.35)'});
    $('body').css('z-index', '-1').append($overlay);
}

function _popup_showPaymentScreen(signedRequest, onPaySuccess, onPayFailure) {
    if (payWindow == null || payWindow.closed) {
        payWindow = window.open(server + '/inapp-pay/pay_start?req=' + signedRequest, 'moz-payment-screen',
                                'menubar=0,location=1,resizable=1,scrollbars=1,status=0,close=1,width=450,height=250,dialog=1');
    } else {
        payWindow.focus();
    }
}

})(typeof exports === 'undefined' ? (this.mozmarket = {}) : exports);
