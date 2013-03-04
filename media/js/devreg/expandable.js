(function() {
    // This is mobile-only.
    if (!$('body').hasClass('mobile')) return;

    // TODO: Make this smarter by injecting the expand controls to the DOM.
    $('.expandable').each(function(i, elm) {
        var $self = $(elm),
            $trigger = $self.find('.showmore'),
            $content = $self.find('.expandcontent');

        // I miss .toggle() :(
        $trigger.click(_pd(function() {
            if ($content.hasClass('expanded')) {
                $content.removeClass('expanded');
                $(this).text(gettext('more...'));
            } else {
                $content.addClass('expanded');
                $(this).text(gettext('less...'));
            }
        }));
    });
})();
