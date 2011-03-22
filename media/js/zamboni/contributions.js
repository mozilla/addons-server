$(document).ready(function() {
    $("#contribute-why").popup("#contribute-more-info", {
        pointTo: "#contribute-more-info"
    });
    if ($('body').attr('data-paypal-url')) {
        $('div.contribute a.suggested-amount').bind('click', function(event) {
             $.ajax({type: 'GET',
                url: $(this).attr('href') + '?result_type=json',
                success: function(json) {
                    $.getScript($('body').attr('data-paypal-url'), function() {
                        dgFlow = new PAYPAL.apps.DGFlow();
                        dgFlow.startFlow(json.url);
                    });
                }
            });
            return false;
        });
    }
    if ($('body').attr('data-paypal-url')) {
        if ($('#paypal-result').length) {
            top_dgFlow = top.dgFlow || (top.opener && top.opener.top.dgFlow);
            if (top_dgFlow !== null) {
                top_dgFlow.closeFlow();
                if (top !== null) {
                    top.close();
                }
            }
        }
    }
});
