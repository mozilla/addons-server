$.fn.truncate = function(opts) {
    opts = opts || {};
    if (z.hasTruncation && (!opts.dir || opts.dir != 'v')) return this;
    var showTitle = opts.showTitle || false,
        dir = (opts.dir && opts.dir[0]) || 'h',
        scrollProp = dir == "h" ? "scrollWidth" : "scrollHeight",
        offsetProp = dir == "h" ? "offsetWidth" : "offsetHeight",
        truncText = opts.truncText || "&hellip;",
        textEl = opts.textEl || false,
        split = [" ",""], counter, success;
    this.each(function() {
        var $el = $(this),
            $tel = textEl ? $(textEl, $el) : $el,
            txt, cutoff,
            oldtext = $tel.attr("oldtext") || $tel.text();
        $tel.attr("oldtext", oldtext);
        for (var i in split) {
            delim = split[i];
            txt = oldtext.split(delim);
            cutoff = txt.length;
            success = false;
            if ($tel.attr("oldtext")) {
                $tel.text(oldtext);
            }
            if ((this[scrollProp] - this[offsetProp]) < 2) {
                $el.removeClass("truncated");
                break;
            }
            var chunk = Math.ceil(txt.length/2), oc=0, wid, delim;
            for (counter = 0; counter < 15; counter++) {
                $tel.html(escape_(txt.slice(0,cutoff).join(delim)) + truncText);
                wid = (this[scrollProp] - this[offsetProp]);
                if (cutoff < 1) {
                    break;
                } else if (wid < 2 && chunk == oc) {
                    if (dir == 'h' || (delim == '' && this["scrollWidth"] < this["offsetWidth"])) {
                        success = true;
                        $el.addClass("truncated");
                        break;
                    }
                } else if (wid > 1) {
                    cutoff -= chunk;
                } else {
                    cutoff += chunk;
                }
                oc = chunk;
                chunk = Math.ceil(chunk/2);
            }
            if (success) break;
        }
        if (showTitle && oldtext != $tel.text()) {
            $tel.attr("title", oldtext);
        }
    });
    return this;
};
$.fn.untruncate = function() {
    this.each(function() {
        var $el = $(this),
            oTxt = $el.attr("oldtext");
        if (oTxt) {
            $el.text(oTxt);
        }
    });
    return this;
};
$.fn.lineclamp = function(lines) {
    // This function limits the number of visible `lines` of text. Overflown
    // text is gracefully ellipsed: http://en.wiktionary.org/wiki/ellipse#Verb.
    if (!lines) {
        return this;
    }
    return this.each(function() {
        var $this = $(this),
            lh = $this.css('line-height');
        if (lh.substr(-2) == 'px') {
            lh = parseFloat(lh.replace('px', ''));
            $this.css({'max-height': Math.ceil(lh) * lines,
                       'overflow': 'hidden',
                       'text-overflow': 'ellipsis'})
                 .truncate({dir: 'v'});
        }
    });
};
$.fn.linefit = function() {
    // This function shrinks text to fit on one line.
    var min_font_size = 7;
    return this.each(function() {
        var $this = $(this),
            fs = parseFloat($this.css('font-size').replace('px', '')),
            max_height = parseFloat($this.css('line-height').replace('px', '')),
            height = $this.height();
        while (height > max_height && fs > min_font_size) {
            // Repeatedly shrink the text by 0.5px until all the text fits.
            fs -= .5;
            $this.css('font-size', fs);
            height = $this.height();
        }
    });
};
