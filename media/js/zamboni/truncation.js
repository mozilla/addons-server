$.fn.truncate = function(opts) {
    opts = opts || {};
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
        if ($tel.attr("oldtext")) {
            $tel.text(oldtext);
        }
        $tel.attr("oldtext", oldtext);
        for (var i in split) {
            delim = split[i];
            txt = oldtext.split(delim);
            cutoff = txt.length;
            success = false;
            if ((this[scrollProp] - this[offsetProp]) < 2) {
                $el.removeClass("truncated");
                break;
            }
            var chunk = Math.ceil(txt.length/2), oc=0, wid, delim;
            for (counter = 0; counter < 10; counter++) {
                $tel.html(txt.slice(0,cutoff).join(delim)+truncText);
                wid = (this[scrollProp] - this[offsetProp]);
                if (wid < 2 && chunk == oc || cutoff < 1) {
                   success = true;
                   $el.addClass("truncated");
                   break;
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