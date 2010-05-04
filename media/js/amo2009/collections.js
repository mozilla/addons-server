var collections = {};
/**
 * These members need to be set on the collections object:
 *   subscribe_url
 *   unsubscribe_url
 *   adding_text
 *   removing_text
 *   add_text
 *   remove_text
 *
 * Optional:
 *   adding_img
 *   removing_img
 *   remove_img
 *   add_img
 */

(function() {

/** Helpers for recently_viewed. **/

RECENTLY_VIEWED_LIMIT = 5;

/* jQuery extras */
jQuery.extend({
    keys: function(obj) {
        var a = [];
        $.each(obj, function(k) { a.push(k); });
        return a;
    },

    values: function(obj) {
        var a = [];
        $.each(obj, function(k, v) { a.push(v); });
        return a;
    },

    items: function(obj) {
        var a = [];
        $.each(obj, function(k, v) { a.push([k, v]); })
        return a;
    },

    /* Same as the built-in jQuery.map, but doesn't flatten returned arrays.
     * Sometimes you really do want a list of lists.
     */
    fmap: function(arr, callback) {
        var a = [];
        $.each(arr, function(index, el) { a.push(callback(el, index)); });
        return a;
    },

    /* Turn a list of (key, value) pairs into an object. */
    dict: function(pairs) {
        var o = {};
        $.each(pairs, function(i, pair) { o[pair[0]] = pair[1]; });
        return o;
    }
});


/* Return a new array of all the unique elements in `arr`.  Order is preserved,
 * duplicates are dropped from the end of the array.
 *
 * `keyfunc` is called once per element before determining uniqueness, so it
 * can be used to pull out a piece of a larger object. It defaults to the
 * identity function.
 */
var unique = function(arr, keyfunc) {
    if (keyfunc === undefined) {
        var keyfunc = function(e) { return e; };
    }

    /* Iterate backwards so dupes at the back are removed. */
    var o = {};
    $.each(arr.reverse(), function(index, element) {
        o[keyfunc(element)] = [index, element];
    });

    /* Sort by the original indexes, then return the elements. */
    var s = $.values(o).sort(function(a, b){ return a[0] - b[0]; });
    return $.fmap(s.reverse(), function(e) { return e[1]; });
};


/* Maintains a list of unique objects in localStorage sorted by date-added
 * (descending).
 *
 * Options:
 *  limit: max number of items to keep in localStorage (default: 10)
 *  storageKey: the key used for localStorage (default: "recently-viewed")
 *  uniqueFunc: the function passed to `unique` to determine uniqueness
 *              of items (default: the whole object, without date-added)
 */
RecentlyViewed = function(options) {
    var defaults = {
        limit: 10,
        storageKey: 'recently-viewed',
        uniqueFunc: function(e) { return e[1]; }
    };
    $.extend(this, defaults, options);
};

RecentlyViewed.prototype = {
    /* Add a new object to the recently viewed items.
     *
     * Returns the new list of saved items.
     */
    add: function(obj) {
        var arr = this._list();
        /* Date.parse turns Date into an integer for better parsing. */
        arr.push([Date.parse(new Date()), obj]);
        /* Sort by Date added. */
        arr.sort(function(a, b) { return b[0] - a[0]; });
        arr = unique(arr, this.uniqueFunc);
        return this._save(arr);
    },

    /* Fetch the list of saved objects.*/
    list: function() {
        return $.fmap(this._list(), function(x) { return x[1]; });
    },

    /* Save an array to localStorage, maintaining the storage limit. */
    _save: function(arr) {
        arr = arr.slice(0, this.limit);
        localStorage[this.storageKey] = JSON.stringify(arr);
        return arr;
    },

    /* Fetch the internal list of (date, object) tuples. */
    _list: function() {
        var val = localStorage[this.storageKey];
        if (val === null || val === undefined) {
            return [];
        } else {
            return JSON.parse(val);
        }
    }
};


collections.recently_viewed = function() {
    try {
        if (!window.localStorage) { return; }
    } catch(ex) {
        return;
    }

    var recentlyViewed = new RecentlyViewed({
      storageKey: 'recently-viewed-collections',
      uniqueFunc: function(e) { return e[1].uuid; }
    });

    var add_recent = $('#add-to-recents');
    if (add_recent.size()) {
        var o = $.dict($.fmap(['title', 'url', 'uuid'], function(key){
            return [key, $.trim(add_recent.find('.' + key).safeText())];
        }));
        var current_uuid = o.uuid;
        recentlyViewed.add(o);
    } else {
        var current_uuid = '';
    }

    var list = $.map(recentlyViewed.list(), function(e) {
        if (e.uuid != current_uuid) {
            return '<li><a class="collectionitem" href="' + e.url + '">' + e.title + '</a></li>';
        }
    });

    if (list.length != 0) {
        list = list.slice(0, RECENTLY_VIEWED_LIMIT);
        $('#recently-viewed')
          .append('<ul class="addon-collections">' + list.join('') + "</ul>")
          .show();
    }
};


/** Helpers for hijack_favorite_button. **/

var sum = function(arr) {
    var ret = 0;
    $.each(arr, function(_, i) { ret += i; });
    return ret;
};

var modal = function(content) {
    if ($.cookie('collections-leave-me-alone'))
        return;

    var e = $('<div class="modal-subscription">' + content + '</div>');
    e.appendTo(document.body).jqm().jqmAddClose('a.close-button').jqmShow();
    e.find('#bothersome').change(function(){
        // Leave me alone for 1 year (doesn't handle leap years).
        $.cookie('collections-leave-me-alone', true,
                 {expires: 365, path: collections.cookie_path});
        e.jqmHide();
    });
};


collections.hijack_favorite_button = function() {

    var c = collections;

    /* Hijack form.favorite for some ajax fun. */
    $('form.favorite').submit(function(event){
        event.preventDefault();

        // `this` is the form.
        var fav_button = $(this).find('button');
        var previous = fav_button.html();
        var is_fav = fav_button.hasClass('fav');

        /* Kind should be in ['adding', 'removing', 'add', 'remove'] */
        var button = function(kind) {
            var text = c[kind + '_text'];
            /* The listing page doesn't have an inline image, detail page does. */
            if (fav_button.find('img').length) {
                var img = c[kind + '_img'];
                fav_button.html('<img src="' + img + '"/>' + text);
            } else {
                fav_button.html(text);
            }
        };

        /* We don't want the button to shrink when the contents
        * inside change. */
        fav_button.css('min-width', fav_button.outerWidth());
        fav_button.addClass('loading-fav').attr('disabled', 'disabled');
        button(is_fav ? 'removing' : 'adding');
        fav_button.css('min-width', fav_button.outerWidth());

        $.ajax({
            type: "POST",
            data: $(this).serialize(),
            url: is_fav ? c.unsubscribe_url : c.subscribe_url,
            success: function(content){
                if (is_fav) {
                    fav_button.removeClass('fav');
                    button('add');
                } else{
                    modal(content);
                    fav_button.addClass('fav');
                    button('remove');
                }
                // Holla back at the extension.
                bandwagonRefreshEvent();
            },
            error: function(){
                fav_button.html(previous);
            },
            complete: function(){
                fav_button.attr('disabled', '');
                fav_button.removeClass('loading-fav');
            }
        });
    });
};


$(document).ready(collections.recently_viewed);

$(document).ready(function() {
    /* Hijack the voting forms to submit over xhr.
     *
     * On success we get all this HTML back again, so it's replaced with a more
     * up-to-date version of itself.
     */
     var callback = function(e) {
        e.preventDefault();
        var the_form = this;
        $.post(this.action, $(this).serialize(), function(content) {
           $(the_form).closest('.barometer').parent().html(content)
               .find('form').submit(callback);
        });
    };
    $('.user-login .barometer form').submit(callback);
})
})();
