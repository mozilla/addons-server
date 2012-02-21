(function(exports) {
    "use strict";

    exports.houdini = function() {
        // Initialize magic labels.
        $(document).delegate('.houdini.inactive', 'click', _pd(function(e) {
            var $label = $(this);
            $label.removeClass('inactive').addClass('active');
        })).delegate('.houdini.active .done', 'click', _pd(function(e) {
            var $label = $(this).closest('.houdini');
            $label.removeClass('active').addClass('inactive');
            // Replace text with new value.
            $label.find('.output').text($label.find('input').val());
        }));
    };

    // Handle Name and Slug.
    exports.general = function() {
        var $ctx = $('#general-details');
    };

})(typeof exports === 'undefined' ? (this.submit_details = {}) : exports);


$(document).ready(function() {
    submit_details.houdini();
    $('#submit-details').exists(submit_details.general);
});
