/*
JS included by any *remote* web app to enable in-app payments via Mozilla Marketplace

To use this script in your app, read the docs here:
https://developer.mozilla.org/en/Apps/In-app_payments

*/
(function(exports) {
"use strict";

var onPaySuccess, onPayFailure;

exports.buy = function(signedRequest, _onPaySuccess, _onPayFailure) {
    onPaySuccess = _onPaySuccess;
    onPayFailure = _onPayFailure;
    if (typeof navigator.showPaymentScreen == 'undefined') {
        // Define our stub for prototyping.
        navigator.showPaymentScreen = showPaymentScreen;
    }
    navigator.showPaymentScreen(signedRequest, _onPaySuccess, _onPayFailure);
};




// -------------------------------------------------------------
// Delete all of this code. This is just a prototype for demos.
// -------------------------------------------------------------



var server, payWindow;

// Using jQuery for easy prototyping...
if (typeof $ === 'undefined') {
    console.log('This prototype currently requires jQuery');
}

// TODO: we'll eventually hardcode server to marketplace.mozilla.org,
// this is in place for local development and testing.
// WARNING: this is pretty much the most insecure code ever.
setTimeout(function() {
    $('script').each(function(i, elem) {
        var src = $(elem).attr('src');
        if (src.search('mozmarket_proto.js') != -1) {
            server = src.replace(/(https?:\/\/[^\/]+).*/g, '$1');
            // When discovering the server based on a CDN link, convert the URL.
            server = server.replace(/(marketplace)(-dev?)-cdn/g, '$1$2');
        }
    });
}, 1);


function handleMessage(msg) {
    if (msg.origin !== server) {
        console.log('Unexpected origin:', msg.origin);
        return;
    }
    var $overlay = $('#moz-payment-overlay');
    if (payWindow) {
        payWindow.close();
    } else if ($overlay.length) {
        $overlay.remove();
    }
    console.log(msg.data);
    switch (msg.data) {
        case 'moz-pay-success':
            console.log('calling', onPaySuccess);
            if (onPaySuccess) {
                onPaySuccess();
            }
            break;
        case 'moz-pay-failure':
            console.log('calling', onPayFailure);
            if (onPayFailure) {
                onPayFailure();
            }
            break;
        default:
            break;
    }
}

if ( window.addEventListener ) {
    window.addEventListener( "message", handleMessage, false );
} else if ( window.attachEvent ) {
    window.attachEvent( "onmessage", handleMessage );
}


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
