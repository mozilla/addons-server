(function(exports) {
    "use strict";

    exports.houdini = function() {
        // Initialize magic labels.
        $(document).delegate('.houdini.ready .edit', 'click', _pd(function(e) {
            var $label = $(this).closest('.houdini');
            $label.addClass('fading');
            setTimeout(function() {
                $label.removeClass('ready').addClass('active');
            }, 500);
        })).delegate('.houdini.active .done', 'click', _pd(function(e) {
            var $label = $(this).closest('.houdini');
            $label.removeClass('active').addClass('ready');
            // Replace text with new value.
            $label.find('.output').text($label.find('input').val());
        }));
    };

    // Handle Name and Slug.
    exports.nameHoudini = function() {
        var $ctx = $('#general-details');
    };

    exports.privacy = function() {
        // Privacy Policy is required. Maybe I can reuse this elsewhere.
        var $ctx = $('#show-privacy');
        // When the checkbox is clicked ...
        $ctx.delegate('input[type=checkbox]', 'click', function() {
            // Hide the label ...
            $ctx.find('label.checkbox').slideUp(function() {
                // And show the Privacy Policy field ...
                $ctx.find('.brform').slideDown(function() {
                    $ctx.addClass('active');
                });
            });
        });
    };

    var $compat_save_button = $('#compat-save-button'),
        isSubmitAppPage = $('#page > #submit-payment-type').length > 0;

    // Reset selected device buttons and values.
    $('#submit-payment-type h2 a').click(function(e) {
        if ($(this).hasClass('disabled') || $compat_save_button.length) {
            return;
        }

        if (isSubmitAppPage) {
            nullifySelections();
        }
    });

    // When a big device button is clicked, update the form.
    $('#submit-payment-type a.choice').on('click',
        _pd(function() {
            var $this = $(this),
                free_or_paid = this.id.split('-')[0],
                $input = $('#id_' + free_or_paid + '_platforms'),
                old = $input.val() || [],
                val = $this.data('value'),
                nowSelected = old.indexOf(val) === -1;

            if (nowSelected) {
                old.push(val);
            } else {
                delete old[old.indexOf(val)];
            }
            $this.toggleClass('selected', nowSelected);
            $this.find('input').prop('checked', nowSelected);
            $input.val(old);
            $compat_save_button.removeClass('hidden');
            setTabState();
        })
    );

    function nullifySelections() {
        $('#submit-payment-type a.choice').removeClass('selected')
            .find('input').removeAttr('checked');

        $('#id_free_platforms, #id_paid_platforms').val([]);
    }

    // Best function name ever?
    function allTabsDeselected() {
        var freeTabs = $('#id_free_platforms option:selected').length;
        var paidTabs = $('#id_paid_platforms option:selected').length;

        return freeTabs === 0 && paidTabs === 0;
    }

    // Condition to show packaged tab...ugly but works.
    function showPackagedTab() {
        return ($('#id_free_platforms option[value=free-firefoxos]:selected').length &&
               $('#id_free_platforms option:selected').length == 1) ||
               $('#id_paid_platforms option[value=paid-firefoxos]:selected').length ||
               allTabsDeselected();
    }

    // Toggle packaged/hosted tab state.
    function setTabState() {
        if (!$('#id_free_platforms, #id_paid_platforms').length) {
            return;
        }

        // If only free-os or paid-os is selected, show packaged.
        if (showPackagedTab()) {
            $('#packaged-tab-header').css('display', 'inline');
        } else {
            $('#packaged-tab-header').hide();
            $('#hosted-tab-header').find('a').click();
        }
    }

    $(document).on('tabs-changed', function(e, tab) {
        if (tab.id == 'packaged-tab-header') {
            $('.learn-mdn.active').removeClass('active');
            $('.learn-mdn.packaged').addClass('active');
        } else if (tab.id == 'hosted-tab-header') {
            $('.learn-mdn.active').removeClass('active');
            $('.learn-mdn.hosted').addClass('active');
        }
    });

    // Deselect all checkboxes once tabs have been setup.
    if (isSubmitAppPage) {
        $('.tabbable').bind('tabs-setup', nullifySelections);
    } else {
        // On page load, update the big device buttons with the values in the form.
        $('#upload-webapp select').each(function(i, e) {
            $.each($(e).val() || [], function() {
                $('#submit-payment-type #' + this).addClass('selected');
            });
        });
    }

})(typeof exports === 'undefined' ? (this.submit_details = {}) : exports);


$(document).ready(function() {

    // Anonymous users can view the Developer Agreement page,
    // and then we prompt for log in.
    if (z.anonymous && $('#submit-terms').length) {
        var $login = $('.overlay.login');
        $login.addClass('show');
        $('#submit-terms form').on('click', 'button', _pd(function() {
            $login.addClass('show');
        }));
    }

    // Icon previews.
    imageStatus.start(true, false);
    $('#submit-media').on('click', function(){
        imageStatus.cancel();
    });

    if (document.getElementById('submit-details')) {
        //submit_details.general();
        //submit_details.privacy();
        initCatFields();
        initCharCount();
        initSubmit();
        initTruncateSummary();
    }
    submit_details.houdini();
});
