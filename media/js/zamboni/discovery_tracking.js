$(function() {
    $('#learn-more').click(function() {
        dcsMultiTrack('DCS.dcssip', 'services.addons.mozilla.org',
                      'DCS.dcsuri', '/en-US/firefox/discovery/pane/',
                      'WT.ti', 'Link: Learn More',
                      'WT.dl', 99,
                      'WT.z_convert', 'Add-onsVideo'
        );
    });
    $('#promos').delegate('.vid-button a', 'click', _pd(function() {
        dcsMultiTrack('DCS.dcssip', 'services.addons.mozilla.org',
                      'DCS.dcsuri', '/en-US/firefox/discovery/pane/',
                      'WT.ti', 'Link: Watch the Video',
                      'WT.dl', 99,
                      'WT.z_convert', 'Add-onsVideo'
        );
    }));
});
