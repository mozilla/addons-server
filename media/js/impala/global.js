$(function() {
    // load deferred images
    $('img[data-defer-src]').each(function() {
        var $img = $(this);
        $img.attr('src', $img.attr('data-defer-src'));
    });

    $('.site-balloon .close').click(function(e) {
        e.preventDefault();
        $(this).closest('.site-balloon').fadeOut();
    });
});