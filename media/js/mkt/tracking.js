z.page.on('fragmentloaded', function() {
    // Copyright (c) 2012 Webtrends Inc.  All rights reserved.
    window.webtrendsAsyncInit = function() {
        var dcs = new Webtrends.dcs().init({
            dcsid: 'dcsk3ol5yvz5bdu9x8ttypqsj_3o6u',
            domain: 'statse.webtrendslive.com',
            timezone: 0,
            offsite: true,
            download: true,
            downloadtypes: 'xls,doc,pdf,txt,csv,zip,docx,xlsx,rar,gzip,xpi,jar',
            onsitedoms: 'marketplace.mozilla.org',
            plugins: {
                //hm:{src:"//s.webtrends.com/js/webtrends.hm.js"}
            }
        }).track();
    };

    // The webtrends docs don't have this so make sure it works.
    webtrendsAsyncInit();
});
