define('payments', [], function() {
    'use strict';

    var currentPrice;
    var $regions = $('.regions');
    var pricesApiEndpoint = $regions.data('pricelistApiUrl') + '{0}/';

    function getOverlay(opts) {
        var id = opts;
        if (_.isObject(opts)) {
            id = opts.id;
        }
        $('.overlay').remove();
        z.body.addClass('overlayed');
        var overlay = makeOrGetOverlay(opts);
        overlay.html($('#' + id + '-template').html())
               .addClass('show')
               .on('click', '.close', _pd(function() {
                   overlay.trigger('overlay_dismissed').remove();
               }));
        return overlay;
    }

    function setupPaymentAccountOverlay($overlay, onsubmit) {
        $overlay.on('submit', 'form', _pd(function() {
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
                                  .text(parsed_errors[field_error]);
                    }
                    // If the error occurred on an unknown field,
                    // stick the error at the top. Maybe with more detail.
                    if (parsed_errors.__all__ !== null) {
                        var target = $old_overlay.find('#bango-account-errors');
                        $('<div>').addClass('error')
                                  .insertAfter(target)
                                  .text(parsed_errors.__all__);
                    }
                } catch(err) {
                    // There was a JSON parse error, just stick the error
                    // message on the form.
                    $old_overlay.find('#bango-account-errors')
                                .html(error_data.responseText);
                }

                // Re-initialize the form submit binding.
                setupPaymentAccountOverlay($waiting_overlay, onsubmit);
            });
        }));
    }

    function updatePrices() {
        /*jshint validthis:true */
        var $this = $(this);
        var selectedPrice = $this.val() || '';
        var apiUrl = format(pricesApiEndpoint, parseInt(selectedPrice, 10));
        var disabledRegions = $regions.data('disabledRegions');
        var freeWithInAppId = $regions.data('freeWithInappId');

        if (currentPrice == selectedPrice) {
            return;
        }

        // If free with in-app is selected then make the 'No' radio disabled
        // and hide it and make the allow_inapp a hidden field.
        if (selectedPrice == freeWithInAppId) {
            $('input[name=allow_inapp][value=True]').attr('type', 'hidden');
            $('input[name=allow_inapp][value=False]').prop('disabled', true)
                                                     .parent('label').hide();
        } else {
            $('input[name=allow_inapp][value=True]').attr('type', 'radio');
            $('input[name=allow_inapp][value=False]').prop('disabled', false)
                                                     .parent('label').show();
        }

        // Clear out existing price data.
        $regions.find('.local-retail').text('');

        $.ajax({
            url: apiUrl,
            success: function(data) {
                var prices = data.prices || [];
                var tierPrice = data.price;
                var seen = [];
                // Iterate over the prices for the regions
                for (var i=0, j=prices.length; i<j; i++) {
                    var price = prices[i];
                    var region = price.region;
                    var $chkbox = $regions.find('input:checkbox[value=' + region + ']');
                    // Skip if over regions that should be disabled e.g games app in Brazil.
                    if (disabledRegions.indexOf(region) > -1) {
                        continue;
                    }
                    // Enable checkboxes for those that we have price info for.
                    $chkbox.prop('disabled', false)
                           .parent('label').removeClass('disabled')
                           .closest('tr').find('.local-retail')
                           .text(price.price +' '+ price.currency)
                           .toggle($chkbox.prop('checked'));
                    seen.push($chkbox[0]);
                }
                // Disable everything else.
                $regions.find('input[type=checkbox]').not(seen)
                                                     .prop('checked', false)
                                                     .prop('disabled', true)
                                                     .parent('label').addClass('disabled')
                                                     .trigger('change');
            },
            dataType: "json"
        });

        currentPrice = selectedPrice;
    }

    function handleCheckboxChange() {
        /*jshint validthis:true */
        var $this = $(this);
        $this.closest('tr').find('.local-retail').toggle($this.prop('checked'));
    }

    function init() {
        $('#regions').trigger('editLoaded');

        $('.update-payment-type button').click(function() {
            $('input[name=toggle-paid]').val($(this).data('type'));
        });

        var $paid_island = $('#paid-island, #paid-upsell-island, #paid-regions-island');
        var $free_island = $('#regions-island');
        $('#submit-payment-type.hasappendix').on('tabs-changed', function(e, tab) {
            $paid_island.toggle(tab.id == 'paid-tab-header');
            $free_island.toggle(tab.id == 'free-tab-header');
        });

        $('#id_price').on('change', updatePrices)
                      .each(updatePrices);

        $('.regions').on('change', 'input[type=checkbox]', handleCheckboxChange);
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
