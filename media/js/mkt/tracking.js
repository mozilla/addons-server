define('tracking', [], function() {
    // Copyright (c) 2012 Webtrends Inc.  All rights reserved.
    window.webtrendsAsyncInit = function() {
        if (!('Webtrends' in window)) {
            return;
        }
        var dcs = new Webtrends.dcs().init({
            dcsid: 'dcsk3ol5yvz5bdu9x8ttypqsj_3o6u',
            domain: 'statse.webtrendslive.com',
            timezone: 0,
            offsite: true,
            download: true,
            downloadtypes: 'xls,doc,pdf,txt,csv,zip,docx,xlsx,rar,gzip,xpi,jar',
            onsitedoms: 'marketplace.firefox.com',
            plugins: {
                //hm:{src:"//s.webtrends.com/js/webtrends.hm.js"}
            }
        }).track();
    };

    // GA Tracking.
    window._gaq = window._gaq || [];

    _gaq.push(['_setAccount', 'UA-36116321-6']);
    _gaq.push(['_trackPageview']);

    (function() {
        var ga = document.createElement('script');
        ga.type = 'text/javascript';
        ga.async = true;
        ga.src = ('https:' == document.location.protocol ? 'https://ssl' : 'http://www') + '.google-analytics.com/ga.js';
        // I am really not a fan of this - injects GA as the first script element.
        var s = document.getElementsByTagName('script')[0];
        s.parentNode.insertBefore(ga, s);
    })();
});
