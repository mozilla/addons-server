import _ from 'underscore';

export function truncate(el, opts) {
  function text(node, trim) {
    let cn = node.childNodes;
    let t = '';
    if (cn.length) {
      for (let i = 0; i < cn.length; i++) {
        t += text(cn[i]);
      }
    } else {
      t = _.escape(node.textContent);
    }
    if (trim) {
      return t.replace(/^\s+|\s+$/g, '');
    }
    return t;
  }

  function _truncate(el, opts) {
    opts = opts || {};
    if (!opts.dir || opts.dir != 'v') return this;
    let showTitle = opts.showTitle || false;
    let dir = (opts.dir && opts.dir[0]) || 'h';
    let scrollProp = dir == 'h' ? 'scrollWidth' : 'scrollHeight';
    let offsetProp = dir == 'h' ? 'offsetWidth' : 'offsetHeight';
    let truncText = opts.truncText || '&hellip;';
    let trim = opts.trim || false;
    let textEl = opts.textEl || el;
    let split = [' ', ''],
      counter,
      success;
    let txt, cutoff, delim;
    let oldtext = textEl.getAttribute('data-oldtext') || text(textEl, trim);
    textEl.setAttribute('data-oldtext', oldtext);
    for (let i = 0; i < split.length; i++) {
      delim = split[i];
      txt = oldtext.split(delim);
      cutoff = txt.length;
      success = false;
      if (textEl.getAttribute('data-oldtext')) {
        textEl.innerHTML = oldtext;
      }
      if (el[scrollProp] - el[offsetProp] < 1) {
        el.removeAttribute('data-truncated', null);
        break;
      }
      let chunk = Math.ceil(txt.length / 2),
        oc = 0,
        wid;
      for (counter = 0; counter < 15; counter++) {
        textEl.innerHTML = txt.slice(0, cutoff).join(delim) + truncText;
        wid = el[scrollProp] - el[offsetProp];
        if (cutoff < 1) {
          break;
        } else if (wid < 2 && chunk == oc) {
          if (
            dir === 'h' ||
            (delim === '' && el.scrollWidth < el.offsetWidth)
          ) {
            success = true;
            el.setAttribute('data-truncated', true);
            break;
          }
        } else if (wid > 1) {
          cutoff -= chunk;
        } else {
          cutoff += chunk;
        }
        oc = chunk;
        chunk = Math.ceil(chunk / 2);
      }
      if (success) break;
    }
    if (showTitle && oldtext != text(textEl, trim)) {
      textEl.setAttribute('title', oldtext);
    }
  }

  return _truncate;
}
