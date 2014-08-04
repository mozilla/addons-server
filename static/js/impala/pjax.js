
$(function() {
    "use strict";
    var $body = $('body'),
        container = $body.attr('data-pjax-container');

    if ($.support.pjax && $body.attr('data-use-pjax')) {
        $('a').pjax(container, {
            success: function() {
                $('html,body').animate({scrollTop: this.offset().top}, 50);
            }
        });
        // TODO(Kumar) Ajax spinner/loader
        // $(container)
        //     .bind('start.pjax', function() { $('#loading').show() })
        //     .bind('end.pjax',   function() { $('#loading').hide() });
    }
});
