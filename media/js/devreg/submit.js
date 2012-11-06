(function(exports) {
    "use strict";

    function _pd(func) {
        // Prevent-default function wrapper.
        return function(e) {
            e.preventDefault();
            func.apply(this, arguments);
        };
    }

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

    // Reset selected device buttons and values.
    $('#submit-payment-type h2 a').click(function(e) {
        $('#submit-payment-type a.choice').removeClass('selected');
        $('#id_free').val([]);
        $('#id_paid').val([]);
    });


    // When a big device button is clicked, update the form.
    $('#submit-payment-type a.choice').on('click',
        function(event) {
            var $this = $(this),
                $input = $('#id_' + this.id.split('-')[0]),
                old = $input.val() || [],
                val = $this.data('value');

            if (old.indexOf(val) === -1) {
                $this.addClass('selected');
                old.push(val);
                $input.val(old);
            } else {
                $this.removeClass('selected');
                delete old[old.indexOf(val)];
                $input.val(old);
            }
            show_packaged();
            event.preventDefault();
        }
    );

    // Show packaged.
    function show_packaged() {
        if (!$('#id_free, #id_paid').length) {
            return;
        }
        var $target = $('#upload-file hgroup h2');

        // If only free-os or paid-os is selected, show packaged.
        if (($('#id_free option[value=free-os]:selected').length &&
             $('#id_free option:selected').length == 1)   ||
            $('#id_paid option[value=paid-os]:selected').length) {
            $target.eq(1).css({'display': 'inline'});
        } else {
            $target.eq(1).css({'display': 'none'});
        }
    }

    // On page load, update the big device buttons with the values in the form.
    $('#upload-webapp select').each(function(i, e) {
        $.each($(e).val() || [], function() {
            $('#submit-payment-type #' + this).addClass('selected');
        });
    });

    // Hide the packaged tab, if needed, once the tabs have been created.
    $('.tabbable').bind('tabs-setup', function() {
        show_packaged();
    });

})(typeof exports === 'undefined' ? (this.submit_details = {}) : exports);


$(document).ready(function() {

    // Anonymous users can view the Developer Agreement page,
    // and then we prompt for log in.
    if (z.anonymous && $('#submit-terms').length) {
        var $login = $('#login');
        $login.addClass('show');
        $('#submit-terms form').on('click', 'button', _pd(function() {
            $login.addClass('show');
        }));
    }

    // Icon previews.
    imageStatus.start(true, false);
    $('#submit-media').bind('click', function() {
        imageStatus.cancel();
    });

    submit_details.houdini();
    $('#submit-details').exists(function () {
        //submit_details.general();
        //submit_details.privacy();
        initCatFields();
        initCharCount();
        initSubmit();
        initTruncateSummary();
    });
    submit_details.houdini();
});
