(function() {
    var top_opener = (window.opener || window).top;
        top_dgFlow = top_opener.dgFlow;
    if (top_dgFlow) {
        top_opener.jQuery(top_opener).trigger('purchaseerror', [null,
            document.querySelector('#purchase-error-msg').textContent]);
        top_dgFlow.closeFlow();
        window.close();
    }
})();
