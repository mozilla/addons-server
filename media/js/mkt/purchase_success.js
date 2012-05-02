(function() {
    var top_opener = (window.opener || window).top;
        top_dgFlow = top_opener.dgFlow;
    if (top_dgFlow) {
        top_opener.jQuery(top_opener).trigger('purchasecomplete');
        top_dgFlow.closeFlow();
        window.close();
    }
})();