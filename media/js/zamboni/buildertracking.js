// Webtrends tracking for the devhub "Builder and SDK" page.

// Entry to the add-on builder.
$('.jetpack-builder .button').click(function() {
    dcsMultiTrack('DCS.dcssip', 'builder.addons.mozilla.org',
                  'DCS.dcsuri', '/',
                  'WT.ti', 'Link: AddonBuilder',
                  'WT.dl', 99,
                  'WT.z_convert', 'AddonBuilder'
                  );
});

// Tracks downloads of the add-on SDK.
$('.jetpack-sdk .button').click(function() {
    dcsMultiTrack('DCS.dcssip', 'addons.mozilla.org',
                  'DCS.dcsuri', '/en-US/developers/builders/',
                  'WT.ti', 'Download: AddonSDK',
                  'WT.dl', 99,
                  'WT.z_convert', 'AddonSDK'
                  );
});

// Tracks plays of the overview video.
$('#builder-overview').click(function() {
    dcsMultiTrack('DCS.dcssip', 'addons.mozilla.org',
                  'DCS.dcsuri', '/en-US/developers/builders/',
                  'WT.ti', 'Video: BuilderOverView',
                  'WT.dl', 99,
                  'WT.z_convert', 'BuilderOverView'
                  );
});

// Tracks plays of the tutorial video.
$('#builder-tutorial').click(function() {
    dcsMultiTrack('DCS.dcssip', 'addons.mozilla.org',
                  'DCS.dcsuri', '/en-US/developers/builders/',
                  'WT.ti', 'Video: BuilderTutorial',
                  'WT.dl', 99,
                  'WT.z_convert', 'BuilderTutorial'
                  );
});

// Tracks clicks of the documentation link.
$('.cols-light .col-3 a').click(function() {
    dcsMultiTrack('DCS.dcssip', 'addons.mozilla.org',
                  'DCS.dcsuri', '/en-US/developers/docs/sdk/latest/',
                  'WT.ti', 'Link: ExtensiveDocumentation',
                  'WT.dl', 99,
                  'WT.z_convert', 'ExtensiveDocumentation'
                  );
});

// Tracks clicks of the contributions link.
$('.jetpack_footer a').click(function() {
    dcsMultiTrack('DCS.dcssip', 'wiki.mozilla.org',
                  'DCS.dcsuri', '/Jetpack/',
                  'WT.ti', 'Link: Contribution',
                  'WT.dl', 99,
                  'WT.z_convert', 'Contribution'
                  );
});
