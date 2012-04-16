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

        ret.each = function(fn) {
            forEach.call(ret, function(item) {
                fn.call(item);
            });
            return ret;
        };

        console.log('foo');

        ret.on = function(type, handler) {
            ret.each(function() {
                on(this, type, handler)
            });
            return ret;
        };


        ret.css = function(o) {
            if (typeof o == 'object') {
                for (p in o) {
                    ret.each(function() {
                        this.style[p] = o[p];
                    });
                }
                return ret;
            }
            return win.getComputedStyle(ret[0]).getPropertyValue(o);
        };


        ret.attr = function(o) {
            if (typeof o == 'object') {
                for (p in o) {
                    ret.each(function() {
                        this.setAttribute(p, o[p]);
                    });
                }
                return ret;
            }
            return ret[0].getAttribute(o);
        };


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

var server = '{{ settings.SITE_URL }}',
    onPaySuccess, onPayFailure,
    $overlay,
    overlayStyle = 'position:absolute;top:0;left:0;right:0;bottom:0;' +
                   'width:100%;max-width:450px;height:100%;max-height:350px;' +
                   'z-index:2001;margin:auto;border:0';

exports.buy = function(signedRequest, _onPaySuccess, _onPayFailure) {
    onPaySuccess = _onPaySuccess;
    onPayFailure = _onPayFailure;
    if (typeof navigator.showPaymentScreen == 'undefined') {
        // Define our stub for prototyping.
        navigator.showPaymentScreen = showPaymentScreen;
    }
    navigator.showPaymentScreen(signedRequest, _onPaySuccess, _onPayFailure);
};

function closeFlow() {
    var overlay = $overlay[0]
    overlay.parentNode.removeChild(overlay);
}

$.on(window, 'message', handleMessage);

function handleMessage(msg) {
    if (msg.origin !== server) {
        return;
    }
    switch (msg.data) {
        case 'moz-pay-cancel':
            closeFlow();
            if (onPayFailure) {
                onPayFailure();
            }
            break;
        case 'moz-pay-success':
            closeFlow();
            if (onPaySuccess) {
                onPaySuccess();
            }
            break;
        default:
            break;
    }
}

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
    $overlay = $(document.createElement('iframe'));
    $overlay.attr({
        'id': 'moz-payment-overlay',
        'type': 'text/html',
        'src': format('{0}/inapp-pay/pay_start?req={1}', server, signedRequest),
        'style': overlayStyle
    });
    $('body').css({'z-index': '-1'})[0].appendChild($overlay[0]);
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
