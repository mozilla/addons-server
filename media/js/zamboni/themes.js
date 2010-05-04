$(document).ready(function(){
    if (!z.appMatchesUserAgent) {
        return;
    }

    var themeCompat = function() {
        var $el = $(this),
            min = $el.attr('data-min'),
            max = $el.attr('data-max')
            vc = new VersionCompare();
        if (vc.compareVersions(gBrowserVersion, min) < 0
            || vc.compareVersions(gBrowserVersion, max) > 0) {
            $el.addClass('incompatible');
            var msg = format(gettext('This theme is incompatible with your version of {0}'),
                             [z.appName]);
            $el.append('<div class="overlay"><p>' + msg + '</p></div>')
                .hover(function() { $(this).children('.overlay').show(); },
                       function() { $(this).children('.overlay').fadeOut(); });
        }
    };

    $('.browse-thumbs .thumbs li').each(themeCompat);
});
