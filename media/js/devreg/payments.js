define('payments', [], function() {
    'use strict';

    var currentPrice;
    var $regions = $('#region-list');
    var $regionsIsland = $('#regions');
    var $regionCheckboxes = $regions.find('input[type=checkbox]');
    var $regionsChangedWarning = $('#regions-changed');
    var $regionsInappropriateWarning = $('#regions-inappropriate');
    var $before = $regions.find('input[type=checkbox]:disabled');

    var apiErrorMsg = $regions.data('apiErrorMsg');
    var disabledGeneralRegions = $regions.data('disabledGeneralRegions');
    var tierZeroId = $regions.data('tierZeroId');
    var notApplicableMsg = $regions.data('notApplicableMsg');
    var paymentMethods = $regions.data('paymentMethods') || {};
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

    function disableCheckbox() {
        /*jshint validthis:true */
        var $this = $(this);

        $this.prop('disabled', true)
             .closest('label').addClass('disabled');

        // Remove the text, where it shouldn't be displayed.
        $this.closest('tr').find('.local-retail, .local-method').text('');
    }

    function compareDisabledCheckboxes($before) {
        var hasChanged = false;
        var $after = $regions.find('input[type=checkbox]:disabled');

        if ($before.length && $after.length && $before.length === $after.length) {
            $after.each(function() {
                // If current element isn't in $before the state has changed and we can
                // exit the each.
                var beforeIndex = $.inArray(this, $before);
                if (beforeIndex === -1) {
                    hasChanged = true;
                    return false;
                // As soon as a disabled prop doesn't match flag the change and exit each.
                } else if ($(this).prop('disabled') !== $($before[beforeIndex]).prop('disabled')) {
                    hasChanged = true;
                    return false;
                }
            });
        } else if (($before.length || $after.length) && $before.length !== $after.length) {
            hasChanged = true;
        }
        if (hasChanged) {
            $regionsChangedWarning.removeClass('hidden');
        } else {
            $regionsChangedWarning.addClass('hidden');
        }
    }

    function updatePrices(checkForChanges) {

        /*jshint validthis:true */
        var $this = $(this);
        var selectedPrice = $this.val();

        checkForChanges = checkForChanges === false ? checkForChanges : true;

        // Check for NaN which will be caused by selectedPrice being ''.
        if (selectedPrice != 'free') {
            selectedPrice = parseInt(selectedPrice, 10);
            selectedPrice = isNaN(selectedPrice) ? false : selectedPrice;
        }

        // No-op if nothing has changed.
        if (currentPrice === selectedPrice) {
            return;
        }

        // Handle the 'Please select a price' case.
        if (selectedPrice === false) {
            $regionCheckboxes.each(disableCheckbox);
            currentPrice = selectedPrice;
            return;
        }

        // If free with in-app is selected, check "Yes" then make the 'No' radio
        // disabled and hide it. Also hide upsell as that's not relevant.
        if (selectedPrice == 'free') {
            $('input[name=allow_inapp][value=True]').prop('checked', true);
            $('input[name=allow_inapp][value=False]').prop('disabled', true)
                                                     .parent('label').hide();

            // Enable all the checkboxes save for those that should be disabled.
            // e.g. unrated games in Brazil.
            $regionCheckboxes.each(function() {
                $this = $(this);
                if (disabledGeneralRegions.indexOf(parseInt($this.prop('value'), 10)) === -1) {
                    $this.prop('disabled', false).closest('label').removeClass('disabled')
                         .closest('tr').find('.local-method, .local-retail')
                         .text(notApplicableMsg);
                } else {
                    disableCheckbox.call(this);
                }
            });
            $('#paid-upsell-island').hide();
            currentPrice = selectedPrice;

            if (checkForChanges) {
                compareDisabledCheckboxes($before);
            }
            return;
        } else {
            $('#paid-upsell-island').show();
            $('input[name=allow_inapp][value=False]').prop('disabled', false)
                                                     .parent('label').show();
        }

        $.ajax({
            url: format(pricesApiEndpoint, selectedPrice),
            beforeSend: function() {
                $regionsIsland.addClass('loading');
            },
            success: function(data) {
                var prices = data.prices || [];
                var tierPrice = data.price;
                var seen = [];
                // Iterate over the prices for the regions
                for (var i=0, j=prices.length; i<j; i++) {
                    var price = prices[i];
                    var region = price.region;
                    var billingMethodText = paymentMethods[parseInt(price.method, 10)] || '';
                    var $chkbox = $regions.find('input:checkbox[value=' + region + ']');

                    // Skip if over regions that should be disabled e.g an unrated games app in Brazil.
                    if (disabledGeneralRegions.indexOf(region) > -1) {
                        continue;
                    }
                    // Enable checkboxes for those that we have price info for.
                    $chkbox.prop('disabled', false)
                           .closest('label').removeClass('disabled');

                    var $tr = $chkbox.closest('tr');

                    $tr.find('.local-retail')
                       .text(price.price + ' ' + price.currency);

                    $tr.find('.local-method')
                       .text(selectedPrice === tierZeroId ? notApplicableMsg : billingMethodText);

                    seen.push($chkbox[0]);

                }
                // Disable everything else.
                $regionCheckboxes.not(seen).each(disableCheckbox);

                if (checkForChanges) {
                    compareDisabledCheckboxes($before);
                }
            },
            dataType: "json"
        }).fail(function() {
            z.doc.trigger('notify', { 'msg': apiErrorMsg });
        }).always(function() {
            $regionsIsland.removeClass('loading');
        });

        currentPrice = selectedPrice;
    }

    function init() {
        var $priceSelect = $('#id_price');
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

        $priceSelect.on('change', updatePrices);
        updatePrices.call($priceSelect[0], false);
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
