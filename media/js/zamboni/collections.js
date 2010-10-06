/* TODO(davedash): Clean this up, it's copied straight from Remora */

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
    },

    clear: function() {
        delete localStorage[this.storageKey];
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
        var o = $.dict($.fmap(['disp', 'url', 'uuid'], function(key){
            return [key, $.trim(add_recent.attr('data-' + key))];
        }));
        var current_uuid = o.uuid;
        recentlyViewed.add(o);
    } else {
        var current_uuid = '';
    }

    var list = $.map(recentlyViewed.list(), function(e) {
        if (e.uuid != current_uuid) {
            return $('<li></li>').append(
                $('<a class="collectionitem" href="' + e.url + '"></a>')
                .text(e.disp)
            )[0];
        }
    });

    if (list.length != 0) {
        list = list.slice(0, RECENTLY_VIEWED_LIMIT);
        var $ul = $('<ul class="addon-collections"></ul>').append($(list));
        $('#recently-viewed')
          .append($ul)
          .append('<a id="clear-recents" href="#">' +
              gettext('clear recently viewed') +
              "</a>")
          .show();
        $('#clear-recents').click(function (e) {
            e.preventDefault();
            recentlyViewed.clear();
            $('#recently-viewed').hide();
        });
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
        var action = this.action + "/ajax";

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
            url: action,
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
     * On success we update the vote counts,
     * and show/hide the 'Remove' link.
     */
     var vote_in_progress = false;
     var callback = function(e) {
        e.preventDefault();
        if (vote_in_progress) return;
        vote_in_progress=true;
        var the_form = $(this);
        $.post(this.action, $(this).serialize(), function(content, status, xhr) {
            vote_in_progress = false
            if (xhr.status == 200) {
                var barometer = the_form.closest('.barometer');
                var oldvote = $('input.voted', barometer);
                var newvote = $('input[type="submit"]', the_form);

                //If the vote cancels an existing vote, cancel said vote
                if (oldvote.length) {
                    oldvote.get(0).value--;
                    oldvote.removeClass('voted');
                }

                //Render new vote if it wasn't a double
                if (oldvote.get(0) !== newvote.get(0)) {
                    newvote.get(0).value++;
                    newvote.addClass('voted');
                }
            }
        });
    };
    if (z.anonymous) {
        $('.barometer form').submit(function(e) {
            e.preventDefault();
            var the_form = this;
            var dropdown = $('.collection-rate-dropdown', $(the_form).closest('.barometer'));
                if ($(the_form).hasClass('downvote')) {
                    dropdown.addClass('left');
                } else {
                    dropdown.removeClass('left');
                }
                dropdown.detach().appendTo(the_form).show();

            // Clear popup when we click outside it.
            setTimeout(function(){
                function cb(e) {
                    _root = dropdown.get(0);
                    // Bail if the click was somewhere on the popup.
                    if (e.type == 'click' &&
                        _root == e.target ||
                        _.indexOf($(e.target).parents(), _root) != -1) {
                        return;
                    }
                    dropdown.hide();
                    $(document.body).unbind('click newPopup', cb);
                }

                $(document.body).bind('click newPopup', cb);
            }, 0);

        });
    } else {
        $('.barometer form').submit(callback);
    }

})

$(document).ready(function(){
    var c = collections;

    c.adding_img = '/img/amo2009/icons/white-loading-16x16.gif';
    c.adding_text = gettext('Adding to Favorites&hellip;');

    c.removing_img = '/img/amo2009/icons/white-loading-16x16.gif';
    c.removing_text = gettext('Removing Favorite&hellip;');

    c.add_img = '/img/amo2009/icons/buttons/plus-orange-16x16.gif';
    c.add_text = gettext('Add to Favorites');

    c.remove_img = '/img/amo2009/icons/buttons/minus-orange-16x16.gif';
    c.remove_text = gettext('Remove from Favorites');

    c.cookie_path = '/';

    collections.hijack_favorite_button();
});

/* Autocomplete for collection add form. */
addon_ac = $('#addon-ac');
if (addon_ac.length) {
    addon_ac.autocomplete({
        minLength: 3,
        width: 300,
        source: function(request, response) {
          $.getJSON($('#addon-ac').attr('data-src'), {
              q: request.term
          }, response);
        },
        focus: function(event, ui) {
          $('#addon-ac').val(ui.item.label);
          return false;
        },
        select: function(event, ui) {
            $('#addon-ac').val(ui.item.label).attr('data-id', ui.item.id)
            .attr('data-icon', ui.item.icon);
            return false;
        }
    }).data( "autocomplete" )._renderItem = function( ul, item ) {
        if (!$("#addons-list input[value='" + item.id + "']").length) {
            return $( "<li></li>" )
                .data( "item.autocomplete", item )
                .append( '<a><img src="' + item.icon + '"/>&nbsp;<span>' + item.label + "</span></a>" )
                .appendTo( ul );
        }
    };
}

$('#addon-select').click(function() {
    var id = $('#addon-ac').attr('data-id');
    var name = $('#addon-ac').val();
    var icon = $('#addon-ac').attr('data-icon');

    // Verify that we aren't listed already
    if ($('input[name=addon][value='+id+']').length) {
        return false;
    }

    if (id && name && icon) {

        var tr = template('<tr>' +
            '<td class="item">' +
            '<input name="addon" value="{id}" type="hidden">' +
            '<img src="{icon}"><h3>{name}</h3>' +
            '<p class="comments">' +
            '<textarea name="addon_comment"></textarea>' +
            '</p></td>' +
            '<td>' + gettext('Pending') + '</td>' +
            '<td><a title="' + gettext('Add a comment') + '" class="comment">' + gettext('Comment') + '</a></td>' +
            '<td class="remove"><a title="' + gettext('Remove this add-on from the collection') + '" class="remove">' + gettext('Remove') + '</a></td>' +
            '</tr>'
            );
        var str = tr({id: id, name: name, icon: icon});
        $('#addon-select').closest('tbody').append(str);
    }
    $('#addon-ac').val('');
    return false;
});

var table = $('#addon-ac').closest('table')
table.delegate(".remove", "click", function() {
    $(this).closest('tr').remove();
})
.delegate(".comment", "click", function() {
    var row = $(this).closest('tr');
    row.find('.comments').show();
    $('.comments textarea', row).focus();
});

})();

if ($('body.collections-contributors')) {

    var user_row = template('<tr>' +
            '<td>' +
            '<input name="contributor" value="{id}" type="hidden">' +
            '{name}' +
            '</td><td>{email}</td>' +
            '<td class="contributor">Contributor</td>' +
            '<td class="remove"><a title="' + gettext("Remove this user as a contributor") + '" class="remove">' + gettext("Remove") + '</a></td>' +
            '</tr>'
            );

    $('#contributor-ac-button').click(function(e) {
        e.preventDefault();
        var email = $('#contributor-ac').val();
        var src = $('#contributor-ac').attr('data-src');
        var my_id = $('#contributor-ac').attr('data-owner');
        $('#contributor-ac').addClass("ui-autocomplete-loading");
        // TODO(potch): Add a fancy failure case.
        $.get(src, {q: email}, function(d) {

            $('#contributor-ac').removeClass("ui-autocomplete-loading");

            // TODO(potch): gently yell at user if they add someone twice.
            if ($('input[name=contributor][value='+d.id+']').length == 0 &&
                my_id != d.id) {
                var str = user_row({id: d.id, name: d.name, email: email});
                $('#contributor-ac-button').closest('tbody').append(str);
            }

            $('#contributor-ac').val('');
        });
    });

    var table = $('#contributors-list');
    table.delegate(".remove", "click", function() {
        $(this).closest('tr').remove();
    })
    $("#change-owner").popup(".make-owner", {
        callback: function (obj) {
            var $popup = this,
                ct = $(obj.click_target);
            $popup.delegate("#change-owner-cancel", "click", function(e) {
                e.preventDefault();
                $popup.hideMe();
            });
            $popup.attr("data-newowner", ct.parents(".contributor")
                                           .children("input[name='contributor']").val()
            );
            return { pointTo: ct };
        }
    });
    $("#change-owner-submit").click(function(e) {
        e.preventDefault();
        var owner_id = $("#change-owner").attr("data-newowner");
        $("#users-edit form").append('<input type="hidden" name="new_owner" value="' + owner_id + '">').submit();
    });
}

$(document).ready(function() {

    $('#remove_icon').click(function(){
      $.post($(this).attr('href'), {}, function(d){
                    $('#icon_upload .icon_preview img').attr('src', d.icon);
                  });
      $(this).hide();
      return false;
    });

});

$(document).ready(function () {

    var url_customized = false;
    var name_val = $('#id_name').val();

    function load_unicode() {
        var $body = $(document.body);
        $body.append("<script src='" + $body.attr('data-media-url') + "/js/zamboni/unicode.js'></script>");
    }

    $(document).bind('unicode_loaded', function() {
        url_customized = !!$('#id_slug').val() && ($('#id_slug').val() != makeslug(name_val));
        slugify();
    });

    function makeslug(s) {
        var re = new RegExp("[^\w" + z.unicode_letters + "0-9\s-]+","g");
        s = $.trim(s.replace(re, ' '));
        s = s.replace(/[-\s]+/g, '-').toLowerCase();
        return s
    }

    function show_slug_edit(e) {
        $("#slug_readonly").hide();
        $("#slug_edit").show();
        $("#id_slug").focus();
        e.preventDefault();
    }

    function slugify() {
        if (z.unicode_letters) {
            var slug = $('#id_slug');
            if (!url_customized || !slug.val()) {
                var s = makeslug($('#id_name').val())
                slug.val(s);
                name_val = s;
                $('#slug_value').text(s);
            }
        } else {
            load_unicode();
        }
    }

    $('#details-edit form, .collection-create form').delegate('#id_name', 'keyup', slugify)
        .delegate('#id_name', 'blur', slugify)
        .delegate('#edit_slug', 'click', show_slug_edit)
        .delegate('#id_slug', 'change', function() {
            url_customized = true;
            if (!$('#id_slug').val()) {
              url_customized = false;
              slugify();
            }
        });

    /* Add to collection initialization */
    var loginHtml = $("#add-to-collection").html();
    $("#add-to-collection").popup(".widgets .collection-add", {
        width: 200,
        offset: {x: 8},
        callback: function(obj) {
            var $widget = this,
                ct = $(obj.click_target),
                list_url    = ct.attr('data-listurl'),
                remove_url  = ct.attr('data-removeurl'),
                add_url     = ct.attr('data-addurl'),
                form_url    = ct.attr('data-newurl'),
                addon_id    = ct.attr('data-addonid');

            if (z.anonymous) {
                return {pointTo: ct};
            }

            function loadList(e) {
                if (e) e.preventDefault();
                ct.addClass("ajax-loading");
                // Make a call to /collections/ajax/list with addon_id
                $.ajax({
                    url: list_url,
                    data: {'addon_id': addon_id},
                    success: renderList,
                    error: function() {
                        renderList(loginHtml);
                    },
                    dataType: 'html'
                });
            }

            function renderList(data) {
                $widget.removeClass("new-collection");
                $widget.html(data);
                $widget.show();
                ct.removeClass("ajax-loading");
                $("a.outlink", $widget).click(stopPropagation);
                $widget.setWidth(200);
                $widget.setPos(ct);
                $widget.render();
            }

            function handleToggle(e) {
                e.preventDefault();

                var tgt = $(this);
                var data = {'addon_id': addon_id,
                            'id': tgt.attr('data-id')};
                var url = this.className == "selected" ? remove_url
                                                       : add_url;

                if (tgt.hasClass('ajax-loading')) return;
                tgt.addClass('ajax-loading');
                $.post(url, data, function(data) {
                    $widget.removeClass('new-collection');
                    $widget.html(data);
                    $("a.outlink", $widget).click(stopPropagation);
                }, 'html');
            }

            var handleSubmit = function(e) {
                e.preventDefault();
                var tgt = $(this);
                if (ct.hasClass('ajax-loading')) return;
                ct.addClass('ajax-loading');
                form_data = $('#add-to-collection form').serialize();
                $.post(form_url + '?addon_id=' + addon_id, form_data, renderList, 'html');
            };

            var handleNew = function(e) {
                e.preventDefault();
                var tgt = $(this);
                $.get(form_url, {'addon_id': addon_id}, function(d) {
                    $widget.addClass('new-collection');
                    $widget.html(d);
                    $widget.setWidth(410);
                    $widget.setPos(ct);
                    $("#id_name").focus();
                });
            };

            $widget.hideMe();
            $widget.unbind('click.popup', stopPropagation);
            $widget.bind('click.popup', stopPropagation);
            $widget.delegate('#ajax_collections_list li', 'click', handleToggle)
                .delegate('#ajax_new_collection', 'click', handleNew)
                .delegate('#collections-new-cancel', 'click', loadList)
                .delegate('#add-to-collection form', 'submit', handleSubmit)
                .delegate('#id_name', 'keyup', slugify)
                .delegate('#id_name', 'blur', slugify)
                .delegate('#edit_slug', 'click', show_slug_edit)
                .delegate('#id_slug', 'change', function() {
                    url_customized = true;
                    if (!$('#id_slug').val()) {
                      url_customized = false;
                      slugify();
                    }
                });

            loadList();

            return false;
        }
    });

    function stopPropagation(e) {
        e.stopPropagation();
    }

});


$(document).ready(function () {

    // Add to favorites functionality
    $(".widget.favorite").click(function(e) {
        e.preventDefault();
        var widget = $(this);
        var data = {'addon_id': widget.attr('data-addonid')};
        var faved = widget.hasClass("faved");
        var url = faved ? widget.attr('data-removeurl') : widget.attr('data-addurl');
        var condensed = widget.hasClass("condensed");

        if (widget.hasClass('ajax-loading')) return;
        widget.addClass('ajax-loading');

        $.ajax({
            url: url,
            data: data,
            type: 'post',
            success: function(data) {
                widget.removeClass('ajax-loading');
                if (faved) {
                    widget.removeClass("faved");
                    if (condensed) widget.attr('title', gettext('Add to favorites'));
                        else widget.text(widget.attr('data-unfavedtext'));
                } else {
                    widget.addClass("faved");
                    if (condensed) widget.attr('title', gettext('Remove from favorites'));
                        else widget.text(widget.attr('data-favedtext'));
                }
                widget.trigger("tooltip_change");
            },
            error: function(xhr) {
                widget.removeClass('ajax-loading');
            }
        });
    });

    // Colleciton following
    $(".collection_widgets .watch").click(function(e) {
        e.preventDefault();
        var widget = $(this);
        if (widget.hasClass('ajax-loading')) return;
        widget.addClass('ajax-loading');

        var follow_text = gettext("Follow this Collection");

        $.ajax({
            url: this.href,
            type: 'POST',
            success: function(data) {
                widget.removeClass('ajax-loading');
                if (data.watching) {
                    widget.addClass("watching");
                    follow_text = gettext("Stop following");
                } else {
                    widget.removeClass("watching");
                }
                if (widget.hasClass('condensed')) {
                    widget.attr("title", follow_text);
                    widget.trigger("tooltip_change");
                } else {
                    widget.text(follow_text);
                }
            },
            error: function() {
                widget.removeClass('ajax-loading');
            }
        });
    });

    //New sharing interaction
    $("#sharing-popup").popup(".share.widget", {
        width: 280,
        offset: {x: 8},
        callback: function(obj) {
            var ret = {};
            var el = $(obj.click_target);
            var $popup = this;
            var base_url = el.attr('data-base-url');
            var counts = $.parseJSON(el.attr("data-share-counts"));
            $popup.hideMe();
            if (counts) {
                for (s in counts) {
                    if (!counts.hasOwnProperty(s)) continue;
                    var c = counts[s];
                    var $li = $("li." + s, this);
                    $(".share-count", $li).text(c);
                    $(".uniquify", $li).attr("href", base_url + s);
                }
            } else {
                return false;
            }
            ret.pointTo = obj.click_target;
            return ret;
        }
    });

});
