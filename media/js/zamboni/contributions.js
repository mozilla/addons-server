$(document).ready(function() {
    $("#contribute-why").popup("#contribute-more-info", {
        pointTo: "#contribute-more-info"
    });
    if ($('body').attr('data-paypal-url')) {
        $('div.contribute a.suggested-amount').live('click', function(event) {
            var el = this;
            $.getJSON($(this).attr('href') + '&result_type=json',
                function(json) {
                    if (json.paykey) {
                        $.getScript($('body').attr('data-paypal-url'), function() {
                            dgFlow = new PAYPAL.apps.DGFlow();
                            dgFlow.startFlow(json.url);
                        });
                    } else {
                        if (!$('#paypal-error').length) {
                            $(el).closest('div').append('<div id="paypal-error" class="popup"></div>');
                        }
                        $('#paypal-error').text(json.error).popup(el, {pointTo:el}).render();
                    }
                }
            );
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
