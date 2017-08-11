/* Browser Utilities
 * Based on amo2009/addons.js
**/

function BrowserUtils() {
    "use strict";

    var userAgentStrings = {
            'firefox' : /^Mozilla.*(Firefox|Minefield|Namoroka|Shiretoko|GranParadiso|BonEcho|Iceweasel|Fennec|MozillaDeveloperPreview)\/([^\s]*).*$/,
            'seamonkey': /^Mozilla.*(SeaMonkey|Iceape)\/([^\s]*).*$/,
            'mobile': /^Mozilla.*(Fennec|Mobile)\/([^\s]*)$/,
            'thunderbird': /^Mozilla.*(Thunderbird|Shredder|Lanikai)\/([^\s*]*).*$/
        },
        osStrings = {
            'windows': /Windows/,
            'mac': /Mac/,
            'linux': /Linux|BSD/,
            'android': /Android/,
        };

    // browser detection
    var browser = {},
        browserVersion = '',
        pattern, match, i,
        badBrowser = true;
    for (i in userAgentStrings) {
        if (userAgentStrings.hasOwnProperty(i)) {
            pattern = userAgentStrings[i];
            match = pattern.exec(navigator.userAgent);
            browser[i] = !!(match && match.length === 3);
            if (browser[i]) {
                browserVersion = escape_(match[2]);
                badBrowser = false;
            }
        }
    }

    // Seamonkey looks like Firefox but Firefox doesn't look like Seamonkey.
    // If both are true, set Firefox to false.
    if (browser.firefox && browser.seamonkey) {
        browser.firefox = false;
    }

    var os = {},
        platform = "";
    for (i in osStrings) {
        if (osStrings.hasOwnProperty(i)) {
            pattern = osStrings[i];
            os[i] = pattern.test(navigator.userAgent);
            if (os[i]) {
                platform = i;
            }
        }
    }
    if (!platform) {
        os['other'] = !platform;
        platform = "other";
    }

    return {
        "browser": browser,
        "browserVersion": browserVersion,
        "badBrowser": badBrowser,
        "os": os,
        "platform": platform,
    };
}

var VersionCompare = {
    /**
     * Mozilla-style version numbers comparison in Javascript
     * (JS-translated version of PHP versioncompare component)
     * @return -1: a<b, 0: a==b, 1: a>b
     */
    compareVersions: function(a,b) {
        var al = a.split('.'),
            bl = b.split('.'),
            ap, bp, r, i;
        for (i=0; i<al.length || i<bl.length; i++) {
            ap = (i<al.length ? al[i] : null);
            bp = (i<bl.length ? bl[i] : null);
            r = this.compareVersionParts(ap,bp);
            if (r !== 0)
                return r;
        }
        return 0;
    },

    /**
     * helper function: compare a single version part
     */
    compareVersionParts: function(ap,bp) {
        var avp = this.parseVersionPart(ap),
            bvp = this.parseVersionPart(bp),
            r = this.cmp(avp['numA'],bvp['numA']);
        if (r) return r;
        r = this.strcmp(avp['strB'],bvp['strB']);
        if (r) return r;
        r = this.cmp(avp['numC'],bvp['numC']);
        if (r) return r;
        return this.strcmp(avp['extraD'],bvp['extraD']);
    },

    /**
     * helper function: parse a version part
     */
    parseVersionPart: function(p) {
        if (p == '*') {
            return {
                'numA'   : Number.MAX_VALUE,
                'strB'   : '',
                'numC'   : 0,
                'extraD' : ''
                };
        }
        var pattern = /^([-\d]*)([^-\d]*)([-\d]*)(.*)$/,
            m = pattern.exec(p),
            r = {
            'numA'  : parseInt(m[1], 10),
            'strB'   : m[2],
            'numC'   : parseInt(m[3], 10),
            'extraD' : m[4]
            };
        if (r['strB'] == '+') {
            r['numA']++;
            r['strB'] = 'pre';
        }
        return r;
    },

    /**
     * helper function: compare numeric version parts
     */
    cmp: function(an,bn) {
        if (isNaN(an)) an = 0;
        if (isNaN(bn)) bn = 0;
        if (an < bn)
            return -1;
        if (an > bn)
            return 1;
        return 0;
    },

    /**
     * helper function: compare string version parts
     */
    strcmp: function(as,bs) {
        if (as == bs)
            return 0;
        // any string comes *before* the empty string
        if (as === '')
            return 1;
        if (bs === '')
            return -1;
        // normal string comparison for non-empty strings (like strcmp)
        if (as < bs)
            return -1;
        else if(as > bs)
            return 1;
        else
            return 0;
    }
};
