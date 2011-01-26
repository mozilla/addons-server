/* TODO(jbalogh): save from amo2009. */
var UA_PATTERN_FIREFOX = /Mozilla.*(Firefox|Minefield|Namoroka|Shiretoko|GranParadiso|BonEcho|Iceweasel|Fennec|MozillaDeveloperPreview)\/([^\s]*).*$/;
var UA_PATTERN_SEAMONKEY = /Mozilla.*(SeaMonkey|Iceape)\/([^\s]*).*$/;
var UA_PATTERN_MOBILE = /Mozilla.*(Fennec)\/([^\s]*)$/;
var UA_PATTERN_THUNDERBIRD = /Mozilla.*(Thunderbird|Shredder|Lanikai)\/([^\s*]*).*$/;

/* TODO(jbalogh): save from amo2009. */
function VersionCompare() {
    /**
     * Mozilla-style version numbers comparison in Javascript
     * (JS-translated version of PHP versioncompare component)
     * @return -1: a<b, 0: a==b, 1: a>b
     */
    this.compareVersions = function(a,b) {
        var al = a.split('.');
        var bl = b.split('.');

        for (var i=0; i<al.length || i<bl.length; i++) {
            var ap = (i<al.length ? al[i] : null);
            var bp = (i<bl.length ? bl[i] : null);

            var r = this.compareVersionParts(ap,bp);
            if (r != 0)
                return r;
        }

        return 0;
    }

    /**
     * helper function: compare a single version part
     */
    this.compareVersionParts = function(ap,bp) {
        var avp = this.parseVersionPart(ap);
        var bvp = this.parseVersionPart(bp);

        var r = this.cmp(avp['numA'],bvp['numA']);
        if (r) return r;

        r = this.strcmp(avp['strB'],bvp['strB']);
        if (r) return r;

        r = this.cmp(avp['numC'],bvp['numC']);
        if (r) return r;

        return this.strcmp(avp['extraD'],bvp['extraD']);
    }

    /**
     * helper function: parse a version part
     */
    this.parseVersionPart = function(p) {
        if (p == '*') {
            return {
                'numA'   : Number.MAX_VALUE,
                'strB'   : '',
                'numC'   : 0,
                'extraD' : ''
                };
        }

        var pattern = /^([-\d]*)([^-\d]*)([-\d]*)(.*)$/;
        var m = pattern.exec(p);

        var r = {
            'numA'  : parseInt(m[1]),
            'strB'   : m[2],
            'numC'   : parseInt(m[3]),
            'extraD' : m[4]
            };

        if (r['strB'] == '+') {
            r['numA']++;
            r['strB'] = 'pre';
        }

        return r;
    }

    /**
     * helper function: compare numeric version parts
     */
    this.cmp = function(an,bn) {
        if (isNaN(an)) an = 0;
        if (isNaN(bn)) bn = 0;

        if (an < bn)
            return -1;

        if (an > bn)
            return 1;

        return 0;
    }

    /**
     * helper function: compare string version parts
     */
    this.strcmp = function(as,bs) {
        if (as == bs)
            return 0;

        // any string comes *before* the empty string
        if (as == '')
            return 1;

        if (bs == '')
            return -1;

        // normal string comparison for non-empty strings (like strcmp)
        if (as < bs)
            return -1;
        else if(as > bs)
            return 1;
        else
            return 0;
    }
}


/* TODO(jbalogh): save from amo2009. */
/**
 * bandwagon: fire a custom refresh event for bandwagon extension
 * @return void
 */
function bandwagonRefreshEvent() {
    if (document.createEvent) {
        var bandwagonSubscriptionsRefreshEvent = document.createEvent("Events");
        bandwagonSubscriptionsRefreshEvent.initEvent("bandwagonRefresh", true, false);
        document.dispatchEvent(bandwagonSubscriptionsRefreshEvent);
    }
}

/**
 * Contributions Lightbox
 * TODO(jbalogh): save from amo2009.
 */
var contributions = {
    commentlimit: 255, // paypal-imposed comment length limit

    init: function() {
        // prepare overlay content
        var cb = $('#contribute-box');
        var contrib_limit = parseFloat($('#contrib-too-much').attr('data-max-amount'));
        cb.find('li label').click(function(e) {
            e.preventDefault();
            $(this).siblings(':radio').attr('checked', 'checked');
            $(this).children('input:text').focus();
        }).end()
        .find('input:text').keypress(function() {
            $(this).parent().siblings(':radio').attr('checked', 'checked');
        }).end()
        .find('textarea').keyup(function() {
            var txt = $(this).val(),
                limit = contributions.commentlimit,
                counter = $(this).siblings('.commentlen');
            if (txt.length > limit) {
                $(this).val(txt.substr(0, limit));
            }
            counter.text(limit - Math.min(txt.length, limit));
        }).keyup().end()
        .find('#contrib-too-much').hide().end()
        .find('#contrib-too-little').hide().end()
        .find('#contrib-not-entered').hide().end()
        .find('form').submit(function() {
            var contrib_type = $(this).find('input:checked').val();
            if (contrib_type == 'onetime') {
                var amt = $(this).find('input[name="'+contrib_type+'-amount"]').val();
                $(this).find('.error').hide();
                if (isNaN(parseFloat(amt))) {
                    $(this).find('#contrib-not-entered').show();
                    return false;
                }
                if (amt > contrib_limit) {
                    $(this).find('#contrib-too-much').show();
                    return false;
                }
                if (parseFloat(amt) >= 0.01) {
                    $(this).find('#contrib-too-little').show();
                    return false;
                }
            }
            var $self = $(this);
            $.ajax({type: 'GET',
                url: $(this).attr('action') + '?result_type=json',
                data: $(this).serialize(),
                success: function(json) {
                    if (json.paykey) {
                        dgFlow.startFlow(json.url);
                        $self.find('span.cancel a').click()
                    } else {
                        $self.find('#paypal-error').show();
                    }
                }
            });
            return false;
        });

        // enable overlay; make sure we have the jqm package available.
        if (!cb.jqm) {
            return;
        }
        cb.jqm({
                overlay: 100,
                overlayClass: 'contrib-overlay',
                onShow: function(hash) {
                    // avoid bleeding-through form elements
                    if ($.browser.opera) this.inputs = $(':input:visible').css('visibility', 'hidden');
                    // clean up, then show box
                    hash.w.find('.error').hide()
                    hash.w
                        .find('input:text').val('').end()
                        .find('textarea').val('').keyup().end()
                        .find('input:radio:first').attr('checked', 'checked').end()
                        .fadeIn();

                },
                onHide: function(hash) {
                    if ($.browser.opera) this.inputs.css('visibility', 'visible');
                    hash.w.find('.error').hide();
                    hash.w.fadeOut();
                    hash.o.remove();
                },
                trigger: '#contribute-button',
                toTop: true
            })
            .jqmAddClose(cb.find('.cancel a'));

        if (window.location.hash === '#contribute-confirm') {
            $('#contribute-button').click();
        }
    }

}

/* TODO(jbalogh): save from amo2009. */
/* Remove "Go" buttons from <form class="go" */
$(document).ready(function(){
    $('form.go').change(function() { this.submit(); })
        .find('button').hide();
});


// TODO(jbalogh): save from amo2009.
var AMO = {};

// TODO(jbalogh): save from amo2009.
// Hide the beta installer.
$(document).ready(function(){
    $('a[href="#install-beta"]').click(function(e) {
        e.preventDefault();
        $('.install-beta').slideDown('slow').show();
    });
});
