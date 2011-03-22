
/* TODO(jbalogh): save from amo2009. */
/**
 * bandwagon: fire a custom refresh event for bandwagon extension
 * @return void
 */
function bandwagonRefreshEvent() {
    if (document.createEvent) {
        var bandwagonSubscriptionsRefreshEvent = document.createEvent("Events");
        bandwagonSubscriptionsRefreshEvent.initEvent("bandwagonRefresh", true, false);
        document.dispatchEvent(bandwagonSubscriptionsRefreshEvent);
    }
}

/**
 * Contributions Lightbox
 * TODO(jbalogh): save from amo2009.
 */
var contributions = {
    commentlimit: 255, // paypal-imposed comment length limit

    init: function() {
        // prepare overlay content
        var cb = $('#contribute-box');
        var contrib_limit = parseFloat($('#contrib-too-much').attr('data-max-amount'));
        cb.find('li label').click(function(e) {
            e.preventDefault();
            $(this).siblings(':radio').attr('checked', 'checked');
            $(this).children('input:text').focus();
        }).end()
        .find('input:text').keypress(function() {
            $(this).parent().siblings(':radio').attr('checked', 'checked');
        }).end()
        .find('textarea').keyup(function() {
            var txt = $(this).val(),
                limit = contributions.commentlimit,
                counter = $(this).siblings('.commentlen');
            if (txt.length > limit) {
                $(this).val(txt.substr(0, limit));
            }
            counter.text(limit - Math.min(txt.length, limit));
        }).keyup().end()
        .find('#contrib-too-much').hide().end()
        .find('#contrib-too-little').hide().end()
        .find('#contrib-not-entered').hide().end()
        .find('form').submit(function() {
            var contrib_type = $(this).find('input:checked').val();
            if (contrib_type == 'onetime') {
                var amt = $(this).find('input[name="'+contrib_type+'-amount"]').val();
                $(this).find('.error').hide();
                // parseFloat will catch everything except 1@, +amt will though
                if (isNaN(parseFloat(amt)) || ((+amt) != amt)) {
                    $(this).find('#contrib-not-entered').show();
                    return false;
                }
                if (amt > contrib_limit) {
                    $(this).find('#contrib-too-much').show();
                    return false;
                }
                if (parseFloat(amt) < 0.01) {
                    $(this).find('#contrib-too-little').show();
                    return false;
                }
            }
            if ($('body').attr('data-paypal-url')) {
                var $self = $(this);
                $.ajax({type: 'GET',
                    url: $(this).attr('action') + '?result_type=json',
                    data: $(this).serialize(),
                    success: function(json) {
                        if (json.paykey) {
                            $.getScript($('body').attr('data-paypal-url'), function() {
                                dgFlow = new PAYPAL.apps.DGFlow();
                                dgFlow.startFlow(json.url);
                                $self.find('span.cancel a').click();
                            });
                        } else {
                            $self.find('#paypal-error').show();
                        }
                    }
                });
                return false;
            } else {
                return true;
            }
        });

        // enable overlay; make sure we have the jqm package available.
        if (!cb.jqm) {
            return;
        }
        cb.jqm({
                overlay: 100,
                overlayClass: 'contrib-overlay',
                onShow: function(hash) {
                    // avoid bleeding-through form elements
                    if ($.browser.opera) this.inputs = $(':input:visible').css('visibility', 'hidden');
                    // clean up, then show box
                    hash.w.find('.error').hide()
                    hash.w
                        .find('input:text').val('').end()
                        .find('textarea').val('').keyup().end()
                        .find('input:radio:first').attr('checked', 'checked').end()
                        .fadeIn();

                },
                onHide: function(hash) {
                    if ($.browser.opera) this.inputs.css('visibility', 'visible');
                    hash.w.find('.error').hide();
                    hash.w.fadeOut();
                    hash.o.remove();
                },
                trigger: '#contribute-button',
                toTop: true
            })
            .jqmAddClose(cb.find('.cancel a'));

        if (window.location.hash === '#contribute-confirm') {
            $('#contribute-button').click();
        }
    }

}

/* TODO(jbalogh): save from amo2009. */
/* Remove "Go" buttons from <form class="go" */
$(document).ready(function(){
    $('form.go').change(function() { this.submit(); })
        .find('button').hide();
});


// TODO(jbalogh): save from amo2009.
var AMO = {};

// TODO(jbalogh): save from amo2009.
// Hide the beta installer.
$(document).ready(function(){
    $('a[href="#install-beta"]').click(function(e) {
        e.preventDefault();
        $('.install-beta').slideDown('slow').show();
    });
});
