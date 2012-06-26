
// Show the actual URL of outgoing links in the status bar.
// e.g. http://outgoing.mozilla.org/v1/b2d58f443178ce1de2ef80bb57dcc80211232c8b/http%3A//wvtc.net/
// ...will display as http://wvtc.net/
//
$(window).bind('fragmentloaded', function mungeLinks() {
    $('a[href^="http://outgoing.mozilla.org"]').each(function(e) {
        var $a = $(this),
            outgoing = $a.attr('href'),
            dest = unescape(outgoing.split('/').slice(5).join('/'));
        // Change it to the real destination:
        $a.attr('href', dest);
        if (z.capabilities.chromeless) {
            $a.attr('target', '_blank');
        }
        $a.click(function(e) {
            // Change it to the outgoing URL:
            $a.attr('href', outgoing);
            setTimeout(function() {
                // Put back the real destination:
                $a.attr('href', dest);
            }, 100);
            return true;
        });
    });
});
