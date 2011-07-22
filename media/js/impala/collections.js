$(function() {
    if (!$(document.body).hasClass('collections')) {
        return;
    }
    $('.watch').click(_pd(function() {
        var $widget = $(this),
            $parent = $widget.closest('.item');
        if ($widget.hasClass('ajax-loading')) return;
        $widget.addClass('ajax-loading');
        var follow_text = gettext('Follow this Collection');
        $.ajax({
            url: $(this).attr('href'),
            type: 'POST',
            success: function(data) {
                $parent.removeClass('watching');
                $widget.removeClass('ajax-loading');
                if (data.watching) {
                    $parent.addClass('watching');
                    follow_text = gettext('Stop Following');
                    $('<span>', {'text': gettext('Following'),
                                 'class': 'is-watching'}).insertBefore($widget);
                } else {
                    $parent.find('.is-watching').remove();
                }
                $widget.text(follow_text);
            },
            error: function() {
                $widget.removeClass('ajax-loading');
            }
        });
    }));
});
