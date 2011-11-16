(function($) {
    var html = '<a style="width:237px;height:32px;vertical-align:middle;text-align:center;background-color:#000;position:absolute;z-index:5555;left:0;background-image:url(%simg/impala/mozillaorg_censorship_wht.png);background-position:center center;background-repeat:no-repeat;text-indent:-9999px;-moz-transform:rotate(-1deg);-webkit-transform:rotate(-1deg);transform:rotate(-1deg);top:55px;" href="http://www.mozilla.org/sopa/">STOP CENSORSHIP</a>';

    function isACD() {
        var start = new Date('Wed Nov 16 2011 00:00:01'),
            end = new Date('Thu Nov 17 2011 00:00:01'),
            now = new Date();
        return (start < now && now < end);
    }

    function isEnUS() {
        return document.location.pathname.indexOf('/en-US/') === 0;
    }

    if (isACD() && isEnUS()) {
        $('#masthead').append(interpolate(html, [$('body').data('media-url')]));
    }

}(jQuery));
