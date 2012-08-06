/*
JS included by any *remote* web app to enable interaction
with the Firefox Marketplace.

This currently supports
* in-app payments.
  Check out the documentation to learn more:
  https://developer.mozilla.org/en/Apps/In-app_payments
* receipt verification.
  Docs: https://github.com/mozilla/receiptverifier

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
            for (var p in s) {
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

{% for name, source in vendor_js %}
// Start embedding source for {{ name }}

{{ source|safe }}

// Finish embedding source for {{ name }}
{% endfor %}

// in-app payments implementation.
var server = '{{ settings.SITE_URL }}',
    overlay,
    def,
    inappRequest;

exports.buy = function(_onPaySuccess, _onPayFailure) {
    if (typeof navigator.showPaymentScreen == 'undefined') {
        // Define our stub for prototyping.
        navigator.showPaymentScreen = showPaymentScreen;
    }
    navigator.showPaymentScreen(_onPaySuccess, _onPayFailure);
    inappRequest = {
        success: _onPaySuccess,
        failure: _onPayFailure,
        sign: function(_signedRequest) {
            signTransaction(_signedRequest);
        },
        cancel: function() {
            cancelTransaction();
        }
    };
    return inappRequest;
};

function closeFlow() {
    overlay.close();
}

$.on(window, 'message', handleMessage);

function handleMessage(msg) {
    if (msg.origin !== server) {
        return;
    }
    switch (msg.data) {
        case 'moz-pay-cancel':
            closeFlow();
            if ("failure" in inappRequest) {
                inappRequest.failure();
            }
            break;
        case 'moz-pay-success':
            closeFlow();
            if ("success" in inappRequest) {
                inappRequest.success();
            }
            break;
        default:
            break;
    }
}

function cancelTransaction() {
    inappRequest.failure();
    closeFlow();
}

function signTransaction(signedRequest) {
    var flowURL = $.fmt('{0}/inapp-pay/pay_start?req={1}',
                        server, signedRequest);
    overlay.location = flowURL;
}

function showPaymentScreen(onPaySuccess, onPayFailure) {
    if (overlay) {
        cancelTransaction();
    }
    var lobbyURL = $.fmt('{0}/inapp-pay/lobby', server);
    var options = "menubar=no,width={2},innerHeight=200,toolbar=no," +
                  "status=no,resizable=no,left={0},top={1}";

    // center the window!
    var width = Math.min(window.outerHeight, 384),
        left = (window.screenX + window.outerWidth - width) / 2,
        top = (window.screenY + window.outerHeight - 200) * .382;
    overlay = window.open(lobbyURL, 'paymentWindow', $.fmt(options, ~~left, ~~top, width));
}

})(typeof exports === 'undefined' ? (this.mozmarket = {}) : exports);
