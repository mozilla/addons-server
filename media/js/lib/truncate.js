var truncate = (function() {
    function text(node, trim) {
        var cn = node.childNodes;
        var t='';
        if (cn.length) {
            for (var i=0; i<cn.length; i++) {
                t += text(cn[i]);
            }
        } else {
            t = node.textContent;
        }
        if (trim) {
            return t.replace(/^\s+|\s+$/g, "");
        }
        return t;
    }

    var hasTruncation = (function() {
        var shim = document.createElement('div');
        shim.innerHTML = '<div style="text-overflow: ellipsis"></div>';
        var s = shim.firstChild.style;
        return 'textOverflow' in s || 'OTextOverflow' in s;
    })();

    function truncate(el, opts) {
        opts = opts || {};
        if (hasTruncation && (!opts.dir || opts.dir != 'v')) return this;
        var showTitle = opts.showTitle || false;
        var dir = (opts.dir && opts.dir[0]) || 'h';
        var scrollProp = dir == "h" ? "scrollWidth" : "scrollHeight";
        var offsetProp = dir == "h" ? "offsetWidth" : "offsetHeight";
        var truncText = opts.truncText || "&hellip;";
        var trim = opts.trim || false;
        var textEl = opts.textEl || el;
        var split = [" ",""], counter, success;
        var txt, cutoff, delim;
        var oldtext = textEl.getAttribute("data-oldtext") || text(textEl, trim);
        textEl.setAttribute("data-oldtext", oldtext);
        for (var i=0; i<split.length; i++) {
            delim = split[i];
            txt = oldtext.split(delim);
            cutoff = txt.length;
            success = false;
            if (textEl.getAttribute("data-oldtext")) {
                textEl.innerHTML = oldtext;
            }
            if ((el[scrollProp] - el[offsetProp]) < 1) {
                el.removeAttribute("data-truncated", null);
                break;
            }
            var chunk = Math.ceil(txt.length/2), oc=0, wid;
            for (counter = 0; counter < 15; counter++) {
                textEl.innerHTML = txt.slice(0,cutoff).join(delim) + truncText;
                wid = (el[scrollProp] - el[offsetProp]);
                if (cutoff < 1) {
                    break;
                } else if (wid < 2 && chunk == oc) {
                    if (dir === 'h' || (delim === '' && el.scrollWidth < el.offsetWidth)) {
                        success = true;
                        el.setAttribute("data-truncated", true);
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
        if (showTitle && oldtext != text(textEl, trim)) {
            textEl.setAttribute("title", oldtext);
        }
    }

    return truncate;
})();