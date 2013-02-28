/*
 * .menutrigger triggers this overlay.
 * .menucontent is the ul containing the menu items. This node should have
 *              a data-title="Title of Menu".
 *
 * TODO: Extend this to iterate over all menufiable DOM elms.
*/
(function() {
    var $body = $('body'),
        $overlay = $('<section id="menupicker"></section>');

    // This JS is only relevant to mobile.
    if (!$body.hasClass('mobile')) return;

    function dismiss(e) {
        $overlay.hide();
        $body.removeClass('pickerized');
        e.preventDefault();
    }

    function show(e) {
        $body.addClass('pickerized');
        $overlay.show();
        e.preventDefault();
    }

    (function() {
        var $oldmenu = $('.menucontent').detach(),
            $title = $('<h1>' + $oldmenu.data('title') + '</h1>'),
            $footer = $('<footer><a href="#">' + gettext('Cancel') + '</a></footer>');
        $overlay.append($title);
        $overlay.append($oldmenu);
        $footer.find('a').click(dismiss);
        $overlay.append($footer);
        $body.append($overlay);
    })();

    // Change click to touch.
    $('.menutrigger').click(show);

})();
