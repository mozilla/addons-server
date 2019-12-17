django.jQuery(document).ready(function ($){
    "use strict";

    $(document).ajaxSend(function(event, xhr, ajaxSettings) {
        var csrf;
        // Block anything that starts with 'http:', 'https:', '://' or '//'.
        if (!/^((https?:)|:?[/]{2})/.test(ajaxSettings.url)) {
            // Only send the token to relative URLs i.e. locally.
            csrf = $("input[name='csrfmiddlewaretoken']").val();
            if (csrf) {
                xhr.setRequestHeader('X-CSRFToken', csrf);
            }
        }
    });

    // Recalculate Hash
    $('.recalc').click(function(e) {
        e.preventDefault();
        var $this = $(this);
        $this.html('Recalcing&hellip;');
        $.post($this.attr('href'), function() {
            $this.text('Done!');
        }).fail(function() {
            $this.text('Error :(');
        }).always(function() {
            setTimeout(function() {
                $this.text('Recalc Hash');
            }, 2000);
        });
    });
});
