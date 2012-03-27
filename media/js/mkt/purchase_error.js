(function() {
    var winTop = window.top,
        top_opener = winTop.opener || winTop;
        top_dgFlow = top_opener.dgFlow;
    if (top_dgFlow) {
        top_opener.jQuery(top_opener).trigger('purchaseerror');
        top_dgFlow.closeFlow();
    }
})();