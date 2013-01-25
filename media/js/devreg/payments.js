define('payments', [], function() {
    'use strict';

    function getOverlay(name) {
        $('.overlay').remove();
        z.body.addClass('overlayed');
        var overlay = makeOrGetOverlay(name);
        overlay.html($('#' + name + '-template').html())
               .addClass('show')
               .on('click', '.close', _pd(function() {
                   // TODO: Generalize this with the event listeners in overlay.js.
                   overlay.trigger('overlay_dismissed');
                   z.body.removeClass('overlayed');
                   overlay.remove();
               }));
        return overlay;
    }

    function setupPaymentAccountOverlay($overlay, onsubmit) {
        $overlay.on('submit', 'form', _pd(function(e) {
            var $form = $(this);
            var $waiting_overlay = getOverlay('bango-waiting');
            var $old_overlay = $overlay.children('section');
            $old_overlay.detach();
            $form.find('.error').remove();

            $.post(
                $form.attr('action'), $form.serialize(),
                function(data) {
                    $waiting_overlay.trigger('dismiss');
                    onsubmit.apply($form, [data]);
                }
            ).error(function(error_data) {
                // If there's an error, revert to the form and reset the buttons.

                // We're recycling the variable $waiting_overlay to store
                // the old overlay. That gets cleaned up, though, when we
                // re-call setupBangoForm().
                $waiting_overlay.empty().append($old_overlay);

                try {
                    var parsed_errors = JSON.parse(error_data.responseText);
                    for (var field_error in parsed_errors) {
                        var field = $('#id_' + field_error);
                        $('<div>').addClass('error')
                                  .insertAfter(field)
                                  .text(parsed_errors[field_error].join('\n'));
                    }
                } catch(err) {
                    // There was a JSON parse error, just stick the error
                    // message on the form.
                    $old_overlay.find('#bango-account-errors')
                                .html(error_data.responseText);
                }
            });
        }));
    }

    function init() {
        $('#regions').trigger('editLoaded');

        $('.update-payment-type button').click(function(e) {
            $('input[name=toggle-paid]').val($(this).data('type'));
        });

        var $paid_island = $('#paid-island, #paid-upsell-island');
        $('#submit-payment-type.hasappendix').on('tabs-changed', function(e, tab) {
            $paid_island.toggle(tab.id == 'paid-tab-header');
        });

    }

    return {
        getOverlay: getOverlay,
        setupPaymentAccountOverlay: setupPaymentAccountOverlay,
        init: init
    };
});

if ($('.payments.devhub-form').length) {
    require('payments').init();
    require('payments-enroll').init();
    require('payments-manage').init();
}
