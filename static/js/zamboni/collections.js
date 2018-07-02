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

var $c = $('h2.collection[data-collectionid]');
if ($c.length) {
    $c.find('img').click(function() {
        window.location.hash = 'id=' + $c.attr('data-collectionid');
    })
}

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
        var action = $(this).attr('action') + "/ajax";

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
                fav_button.html('<img src="' + img + '" alt="" />' + text);
            } else {
                fav_button.html(text);
            }
        };

        /* We don't want the button to shrink when the contents
        * inside change. */
        fav_button.css('min-width', fav_button.outerWidth());
        fav_button.addClass('loading-fav').prop('disabled', true);
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
                fav_button.prop('disabled', false);
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
        $.post($(this).attr('action'), $(this).serialize(), function(content, status, xhr) {
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
                    $(document.body).off('click newPopup', cb);
                }

                $(document.body).on('click newPopup', cb);
            }, 0);

        });
    } else {
        $('.barometer form').submit(callback);
    }

});

$(document).ready(function(){
    var c = collections;

    c.adding_img = '/img/icons/white-loading-16x16.gif';
    c.adding_text = gettext('Adding to Favorites&hellip;');

    c.removing_img = '/img/icons/white-loading-16x16.gif';
    c.removing_text = gettext('Removing Favorite&hellip;');

    c.add_img = '/img/icons/buttons/plus-orange-16x16.gif';
    c.add_text = gettext('Add to Favorites');

    c.remove_img = '/img/icons/buttons/minus-orange-16x16.gif';
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
          $('#addon-ac').val(ui.item.name);
          return false;
        },
        select: function(event, ui) {
            $('#addon-ac').val(ui.item.name).attr('data-id', ui.item.id)
            .attr('data-icon', ui.item.icons['32']);
            return false;
        }
    }).data('ui-autocomplete')._renderItem = function(ul, item) {
        if (!$("#addons-list input[value=" + item.id + "]").length) {
            return $('<li>')
                .data('item.autocomplete', item)
                .append('<a><img src="' + item.icons['32'] + '" alt="">' + _.escape(item.name) + '</a>')
                .appendTo(ul);
        } else {
            return $('<li>');
        }
    };
}

$('#addon-ac').keydown(function(e) {
    if (e.which == 13) {
        e.preventDefault();
        $('#addon-select').click();
    }
});
$('#addon-select').click(function(e) {
    e.preventDefault();
    var id = $('#addon-ac').attr('data-id');
    var name = _.escape($('#addon-ac').val());
    var icon = $('#addon-ac').attr('data-icon');

    // Verify that we aren't listed already
    if ($('input[name=addon][value='+id+']').length) {
        return false;
    }

    if (id && name && icon) {

        var tr = template('<tr>' +
            '<td class="item">' +
            '<input name="addon" value="{id}" type="hidden">' +
            '<img src="{icon}" alt=""><h3>{name}</h3>' +
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
});

var table = $('#addon-ac').closest('table');
table.on("click", ".remove", function() {
    $(this).closest('tr').remove();
})
.on("click", ".comment", function() {
    var row = $(this).closest('tr');
    row.find('.comments').show();
    $('.comments textarea', row).focus();
});

})();

$(document).ready(function() {

    $('#remove_icon').click(function(){
        $.ajax({
            url: $(this).attr('href'),
            headers: {"X-CSRFToken": $.cookie('csrftoken')},
            type: "POST",
            success: function(d) { $('#icon_upload .icon_preview img').attr('src', d.icon); }
        });
        $(this).hide();
        return false;
    });

});

$(document).ready(function () {

    var name_val = $('#id_name').val();

    $(document).on('unicode_loaded', function() {
        $('#id_slug').attr('data-customized', (!!$('#id_slug').val() &&
                           ($('#id_slug').val() != makeslug(name_val))) ? 1 : 0);
        slugify();
    });

    $('#details-edit form, .collection-create form')
        .on('keyup', '#id_name', slugify)
        .on('blur', '#id_name', slugify)
        .on('click', '#edit_slug', show_slug_edit)
        .on('change', '#id_slug', function() {
            $('#id_slug').attr('data-customized', 1);
            if (!$('#id_slug').val()) {
                $('#id_slug').attr('data-customized', 0);
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
                $widget.html(data);
                $widget.show();
                ct.removeClass("ajax-loading");
                $("a.outlink", $widget).click(stopPropagation);
                if (!$(".errorlist li", $widget).length)
                    $widget.setWidth(200);
                $widget.setPos(ct);
                $widget.render();
                $widget.on('click', '#ajax_collections_list li', handleToggle)
                       .on('click', '#ajax_new_collection', handleNew)
                       .on('keyup', '#id_name', slugify)
                       .on('blur', '#id_name', slugify)
                       .on('click', '#edit_slug', show_slug_edit)
                       .on('change', '#id_slug', function() {
                           if (!$('#id_slug').val()) {
                             $('#id_slug').attr('data-customized', 0);
                             slugify();
                           } else {
                             $('#id_slug').attr('data-customized', 1);
                           }
                       });
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
                    $widget.html(data);
                    $("a.outlink", $widget).click(stopPropagation);
                }, 'html');
            }

            var handleSubmit = function(e) {
                e.preventDefault();
                var tgt = $(this);
                if (ct.hasClass('ajax-loading')) return;
                ct.addClass('ajax-loading');

                var form_data = {};
                $.each($('#add-to-collection form').serializeArray(), function() {
                    form_data[this.name] = this.value;
                })

                form_data['addon_id'] = addon_id;

                $.post(form_url, form_data, renderList, 'html');
            };

            var handleNew = function(e) {
                e.preventDefault();
                var tgt = $(this);
                $.get(form_url, function(d) {
                    $widget.html(d);
                    $widget.setWidth(410);
                    $widget.setPos(ct);
                    $("#id_name").focus();
                    $('#collections-new-cancel').on('click', loadList);
                    $('#add-to-collection form').on('submit', handleSubmit);
                });
            };

            $widget.hideMe();
            $widget.off('click.popup', stopPropagation);
            $widget.on('click.popup', stopPropagation);

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
            url: $(this).attr('href'),
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
            var base_url = el.attr('data-base-url');
            var $popup = this;
            $popup.find('a.uniquify').each(function(index, item) {
                var $item = $(item);
                $item.attr('href', base_url + $item.attr('data-service-name'));
            });
            $popup.hideMe();
            ret.pointTo = obj.click_target;
            return ret;
        }
    });

    if ($('#details-edit').length && $('div.notification-box').length) {
        $(document).scrollTop($("div.primary").position().top);
    }
});
