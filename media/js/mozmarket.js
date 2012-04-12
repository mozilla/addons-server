/*
JS included by any *remote* web app to enable in-app payments via Mozilla Marketplace

To use this script in your app, read the docs here:
https://developer.mozilla.org/en/Apps/In-app_payments

*/
(function(exports) {
"use strict";
// embedded https://github.com/potch/picolib
var $ = (function(win, doc, undefined) {

    function pico(sel) {
        var ret,
            p,
            forEach = Array.prototype.forEach;

        ret = sel.nodeType ? [sel] : doc.querySelectorAll(sel);

        ret.each = (function(fn) {
            forEach.call(this, function(item) {
                fn.call(item);
            });
            return this;
        }).bind(ret);


        ret.on = (function(type, handler) {
            this.each(function() {
                on(this, type, handler)
            });
            return this;
        }).bind(ret);


        ret.css = (function(o) {
            if (typeof o == 'object') {
                for (p in o) {
                    this.each(function() {
                        this.style[p] = o[p];
                    });
                }
                return this;
            }
            return win.getComputedStyle(this[0]).getPropertyValue(o);
        }).bind(ret);


        ret.attr = (function(o) {
            if (typeof o == 'object') {
                for (p in o) {
                    this.each(function() {
                        this.setAttribute(p, o[p]);
                    });
                }
                return this;
            }
            return this[0].getAttribute(o);
        }).bind(ret);


        return ret;
    };

    var on = pico.on = function(el, type, handler) {
        el.addEventListener(type, function(e) {
            handler.call(e.target, e);
        }, false);
    };

    return pico;
})(window, document);

var format = (function() {
    var re = /\{([^}]+)\}/g;
    return function(s, args) {
        if (!args) return;
        if (!(args instanceof Array || args instanceof Object))
            args = Array.prototype.slice.call(arguments, 1);
        return s.replace(re, function(_, match){ return args[match]; });
    };
})();



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

// if (window.addEventListener ) {
//     window.addEventListener( "message", handleMessage, false );
// } else if ( window.attachEvent ) {
//     window.attachEvent( "onmessage", handleMessage );
// }

var overlayStyle = 'position:absolute;top:0;left:0;right:0;bottom:0;' +
                   'width:100%;max-width:450px;height:100%;max-height:350px;' +
                   'z-index:2001;margin:auto;border:0';

function showPaymentScreen(signedRequest, onPaySuccess, onPayFailure) {
    // check cookie for marketplace session?
    // _popup_showPaymentScreen(signedRequest, onPaySuccess, onPayFailure);
    _overlay_showPaymentScreen(signedRequest, onPaySuccess, onPayFailure);
}

function _overlay_showPaymentScreen(signedRequest, onPaySuccess, onPayFailure) {
    var overlay = $('#moz-payment-overlay')[0];
    if (overlay) {
        overlay.parentNode.removeChild(overlay);
    }
    var $overlay = $(document.createElement('iframe'));
    $overlay.attr({
        'id': 'moz-payment-overlay',
        'type': 'text/html',
        'src': format('{0}/inapp-pay/pay_start?req={1}', 'http://marketplace-dev.allizom.org', signedRequest),
        'style': overlayStyle
    });
    $('body').css({'z-index': '-1'})[0].appendChild($overlay[0]);
}

function _popup_showPaymentScreen(signedRequest, onPaySuccess, onPayFailure) {
    if (payWindow == null || payWindow.closed) {
        payWindow = window.open('http://marketplace-dev.allizom.org/inapp-pay/pay_start?req=' + signedRequest, 'moz-payment-screen',
                                'menubar=0,location=1,resizable=1,scrollbars=1,status=0,close=1,width=450,height=250,dialog=1');
    } else {
        payWindow.focus();
    }
}

})(typeof exports === 'undefined' ? (this.mozmarket = {}) : exports);
