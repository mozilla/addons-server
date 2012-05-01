(function(exports) {
"use strict";
/*
 * A simpler boomerang: https://github.com/yahoo/boomerang that just
 * does navigation timing. Requires jquery.
 *
 * Copied from django-statsd.
 */

var perf = window.performance || window.msPerformance ||
           window.webkitPerformance || window.mozPerformance;

var send = function(data) {
    if (perf) {
        var timings = $('body').attr('data-collect-timings');
        if (timings) {
            timings = timings.split(':', 2);
            data.client = 'stick';
            if (Math.random() < parseFloat(timings[1])) {
                $.post(timings[0], data);
            }
        }
    }
};

exports.basic = function() {
    /* Sends the timing data to the given URL */
    send({
        'window.performance.timing.navigationStart': perf.timing.navigationStart,
        'window.performance.timing.domComplete': perf.timing.domComplete,
        'window.performance.timing.domInteractive': perf.timing.domInteractive,
        'window.performance.timing.domLoading': perf.timing.domLoading,
        'window.performance.navigation.redirectCount': perf.navigation.redirectCount,
        'window.performance.navigation.type': perf.navigation.type,
    });
};

exports.custom = function(data) {
    data['window.performance.timing.navigationStart'] = 0;
    send(data);
};

})(typeof exports === 'undefined' ? (this.stick = {}) : exports);
