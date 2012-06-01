/*
JS included by any *remote* web app to enable interaction
with the Mozilla Marketplace.

This currently supports in-app payments.
Check out the documentation to learn more:
https://developer.mozilla.org/en/Apps/In-app_payments
*/
(function(exports) {
"use strict";
// embedded https://github.com/potch/mu.js
var $ = (function(win, doc) {

    var call = 'call',
        obj = 'object',
        length = 'length',
        qsa = 'querySelectorAll',
        forEach = 'forEach',
        parentNode = 'parentNode';

    function mu(sel) {
        var i,
            ret = sel.nodeType ? [sel] : arr(doc[qsa](sel));

        function prop(css_if_true) {
            return function(o) {
                if (typeof o == obj) {
                    for (i in o) {
                        ret[forEach](function(el) {
                            if (css_if_true) {
                                el.style.setProperty(i, o[i]);
                            } else {
                                el.setAttribute(i, o[i]);
                            }
                        });
                    }
                    return ret;
                }
                if (css_if_true) {
                    return win.getComputedStyle(ret[0]).getPropertyValue(o);
                } else {
                    return ret[0].getAttribute(o);
                }
            };
        }

        extend(ret, {
            on : function(type, handler) {
                ret[forEach](function(el) {
                    on(el, type, handler)
                });
                return ret;
            },
            delegate : function(type, sel, handler) {
                ret[forEach](function(dEl) {
                    on(dEl, type, function(e,t) {
                        var matches = dEl[qsa](sel);
                        for (var el = t; el[parentNode] && el != dEl; el = el[parentNode]) {
                            for (i=0;i<matches[length];i++) {
                                if (matches[i] == el) {
                                    handler[call](el, e);
                                    return;
                                }
                            }
                        }
                    });
                });
                return ret;
            },
            css : prop(1),
            attr : prop()
        });

        return ret;
    };

    var fmt_re = /\{([^}]+)\}/g,
        arr = mu.arr = function(a, i) {
            return Array.prototype.slice[call](a,i||0);
        },
        extend = mu.extend = function(d, s) {
            for (p in s) {
                d[p] = s[p];
            }
        },
        on = mu.on = function(obj, type, handler) {
            obj.addEventListener(type, function(e) {
                handler(e, e.target);
            }, false);
        };

        mu.fmt = function(s, vals) {
            if (!(vals instanceof Array || vals instanceof Object))
                vals = arr(arguments, 1);
            return s.replace(fmt_re, function(_, match){ return vals[match]; });
        };

    return mu;
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

})(typeof exports === 'undefined' ? (this.mozmarket = {}) : exports);
