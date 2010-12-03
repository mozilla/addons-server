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
        .find('form').submit(function() {
            var contrib_type = $(this).find('input:checked').val();
            if (contrib_type == 'onetime' || contrib_type == 'monthly') {
                var amt = $(this).find('input[name="'+contrib_type+'-amount"]').val();
                if (amt > contrib_limit) {
                    $(this).find('#contrib-too-much').show();
                    return false;
                }
            }
            return true;
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
                    hash.w
                        .find('input:text').val('').end()
                        .find('textarea').val('').keyup().end()
                        .find('input:radio:first').attr('checked', 'checked').end()
                        .fadeIn();
                },
                onHide: function(hash) {
                    if ($.browser.opera) this.inputs.css('visibility', 'visible');
                    hash.w.find('#contrib-too-much').hide();
                    hash.w.fadeOut();
                    hash.o.remove();
                },
                trigger: '#contribute-button',
                toTop: true
            })
            .jqmAddClose(cb.find('.cancel a'));
    }
}

/* TODO(jbalogh): save from amo2009. */
/* Remove "Go" buttons from <form class="go" */
$(document).ready(function(){
    $('form.go').change(function() { this.submit(); })
        .find('button').hide();
});


/* TODO(jbalogh): delete with bug 616239. */
// Draw a thermometer for contribution pledges in the selected canvas element.
// Configuration parameters are taken from 'data-' attributes:
//     data-ratio, data-radius
jQuery.fn.thermometer = function() {
    this.each(function() {
        var canvas = this;
        if (!canvas.getContext) return;

        var ctx = canvas.getContext('2d');

        // Draws the outline of the thermometer.
        // Options: {x, y, len, radius}
        var thermometer = function (opts) {
            /* The big circle goes from 30º to 330º, so we go horizontal at
             * y +- (radius / 2).  Thus, the smaller half-circle gets a
             * radius of radius / 2.  Trigonometry!
             */
            ctx.beginPath();
            ctx.arc(opts.x, opts.y, opts.radius,
                    Math.PI / 6, Math.PI * (11 / 6), false);
            ctx.arc(opts.x + opts.len, opts.y, opts.radius / 2,
                    Math.PI * (3 / 2), Math.PI / 2, false);
            ctx.closePath();
        }

        // HTML5 data attribute helper.
        var dataset = function (element, name) {
            return JSON.parse(element.getAttribute('data-' + name));
        };

        var ratio = Math.max(0, Math.min(1, dataset(canvas, 'ratio'))),
            radius = dataset(canvas, 'radius'),
            padding = 10,
            length = ctx.canvas.width - ((radius + padding) * 2),
            start_x = radius + padding,
            start_y = ctx.canvas.height / 2,
            opts = {x: start_x, y: start_y, len: length * ratio,
                    radius: radius - 4}

        // The inner fill (the mercury).  We add a second circle so the bulb
        // gets filled in more.  It's just for looks.
        if (ratio > 0) {
            ctx.fillStyle = '#3dacfd';
            thermometer(opts);
            ctx.fill();
            ctx.arc(opts.x, opts.y, opts.radius + 2, 0, Math.PI * 2, false);
            ctx.fill();
        }

        // The outer container (the thermometer).
        opts = $.extend(opts, {len: length, radius: radius});
        ctx.strokeStyle = '#739fb9'; // Border color.

        // Glassy gradient overlaying the inner fill.
        var gradient = ctx.createLinearGradient(0, opts.y - opts.radius,
                                                0, opts.y + opts.radius);
        gradient.addColorStop(0, 'rgba(255, 255, 255, 0.5)');
        gradient.addColorStop(1, 'rgba(255, 255, 255, 0)');

        // Draw the container.
        thermometer(opts);
        ctx.stroke();
        ctx.fillStyle = gradient;
        ctx.fill();

        // Tick marks at 25%, 50%, 75%;
        ctx.strokeStyle = '#666';  // Darker to compete with the fill color.
        for (var i = 1; i < 4; i++) {
            var x = start_x + i * (length / 4);
            ctx.beginPath();
            ctx.moveTo(x, start_y);
            ctx.lineTo(x, start_y + (radius / 2));
            ctx.stroke();
        }
    });
    return this;
}

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
