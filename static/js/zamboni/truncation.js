$.fn.truncate = function(opts) {
    this.each(function() {
        truncate(this, opts);
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
        if (typeof lh == 'string' && lh.substr(-2) == 'px') {
            lh = parseFloat(lh.replace('px', ''));
            var maxHeight = Math.ceil(lh) * lines,
                truncated;
            if ((this.scrollHeight - maxHeight) > 2) {
                $this.css({'height': maxHeight + 2, 'overflow': 'hidden',
                           'text-overflow': 'ellipsis'});
                // Add an ellipsis.
                $this.truncate({dir: 'v'});
            } else {
                $this.css({'max-height': maxHeight, 'overflow': 'hidden',
                           'text-overflow': 'ellipsis'});
            }
        }
    });
};
$.fn.linefit = function(lines) {
    // This function shrinks text to fit on one line.
    var min_font_size = 7;
    lines = lines || 1;
    return this.each(function() {
        var $this = $(this),
            fs = parseFloat($this.css('font-size').replace('px', '')),
            max_height = Math.ceil(parseFloat($this.css('line-height').replace('px', ''))) * lines,
            height = $this.height();
        while (height > max_height && fs > min_font_size) {
            // Repeatedly shrink the text by 0.5px until all the text fits.
            fs -= .5;
            $this.css('font-size', fs);
            height = $this.height();
        }
    });
};
