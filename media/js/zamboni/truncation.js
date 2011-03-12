$.fn.vtruncate = function(opts) {
    opts = opts || {};
    var showTitle = opts.showTitle || false,
        truncText = opts.truncText || "&hellip;",
        split = [" ",""], counter, success;
    this.each(function() {
        var $el = $(this),
            oldtext = $el.attr("oldtext") || $el.text(),
            txt, cutoff;
        if ($el.attr("oldtext")) {
            oldtext = unescape(oldtext);
            $el.text(oldtext);
        }
        $el.attr("oldtext", escape(oldtext));
        for (var i in split) {
            delim = split[i];
            txt = oldtext.split(delim);
            cutoff = txt.length;
            success = false;
            if ((this.scrollHeight - this.offsetHeight) < 2) {
                $el.removeClass("truncated");
                break;
            }
            var chunk = Math.ceil(txt.length/2), oc=0, wid, delim;
            for (counter = 0; counter < 10; counter++) {
                $el.html(txt.slice(0,cutoff).join(delim)+truncText);
                wid = (this.scrollHeight - this.offsetHeight);
                if ((wid < 2 && chunk == oc) || cutoff < 1) {
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
        if (showTitle) {
            $el.attr("title", oldtext);
        }
    });
    return this;
};

$.fn.htruncate = function(opts) {
    opts = opts || {};
    var showTitle = opts.showTitle || false,
        truncText = opts.truncText || "&hellip;",
        textEl = opts.textEl || false;
        split = [" ",""];
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
            var done = (this.scrollWidth - this.offsetWidth) < 2,
                chunk = Math.ceil(txt.length/2), oc=0, wid, delim;
            while (!done) {
                $tel.html(txt.slice(0,cutoff).join(delim)+truncText);
                wid = (this.scrollWidth - this.offsetWidth);
                if (wid < 2 && chunk == oc) {
                   done = true;
                } else if (wid > 1) {
                   cutoff -= chunk;
                } else {
                   cutoff += chunk;
                }
                oc = chunk;
                chunk = Math.ceil(chunk/2);
            }
        }
        if (showTitle && oldtext != $tel.text()) {
            $tel.attr("title", oldtext);
        }
    });
    return this;
};