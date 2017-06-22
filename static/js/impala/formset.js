function updateTotalForms(prefix, inc) {
    var $totalForms = $('#id_' + prefix + '-TOTAL_FORMS'),
        $maxForms = $('#id_' + prefix + '-MAX_NUM_FORMS'),
        inc = inc || 1,
        num = parseInt($totalForms.val(), 10) + inc;
    if ($maxForms.length && $maxForms.val().length) {
        var maxNum = parseInt($maxForms.val(), 10);
        if (num > maxNum) {
            return num - 1;
        }
    }
    $totalForms.val(num);
    return num;
}


/**
 * zAutoFormset: handles Django formsets with autocompletion like a champ!
 * by cvan
 */

(function($) {

$.zAutoFormset = function(o) {

    o = $.extend({
        delegate: document.body,   // Delegate (probably some nearby parent).

        forms: null,               // Where all the forms live (maybe a <ul>).

        extraForm: '.extra-form',  // Selector for element that contains the
                                   // HTML for extra-form template.

        maxForms: 3,               // Maximum number of forms allowed.

        prefix: 'form',            // Formset prefix (Django default: 'form').

        hiddenField: null,         // This is the name of a (hidden) field
                                   // that will contain the value of the
                                   // formPK for each newly added form.

        removeClass: 'remove',     // Class for button triggering form removal.

        formSelector: 'li',        // Selector for each form container.

        formPK: 'id',              // Primary key for initial forms.

        src: null,                 // Source URL of JSON search results.

        input: null,               // Input field for autocompletion search.

        searchField: 'q',          // Name of form field for search query.

        minSearchLength: 3,        // Minimum character length for queries.

        width: 300,                // Width (pixels) of autocomplete dropdown.

        addedCB: null,             // Callback for each new form added.

        removedCB: null,           // Callback for each form removed.

        autocomplete: null         // Custom handler you can provide to handle
                                   // autocompletion yourself.
    }, o);

    var $delegate = $(o.delegate),
        $forms = o.forms ? $delegate.find(o.forms) : $delegate,
        $extraForm = $delegate.find(o.extraForm),
        formsetPrefix = o.prefix,
        hiddenField = o.hiddenField,
        removeClass = o.removeClass,
        formSelector = o.formSelector,
        formPK = o.formPK,
        src = o.src || $delegate.attr('data-src'),
        $input = o.input ? $(o.input) : $delegate.find('input.autocomplete'),
        searchField = o.searchField,
        minLength = o.minSearchLength,
        $maxForms = $('#id_' + formsetPrefix + '-MAX_NUM_FORMS'),
        width = o.width,
        addedCB = o.addedCB,
        removedCB = o.removedCB,
        autocomplete = o.autocomplete,
        maxItems;

        if ($maxForms.length && $maxForms.val()) {
            maxItems = parseInt($maxForms.val(), 10);
        } else if (o.maxForms) {
            maxItems = o.maxForms;
        }

    function findItem(item) {
        if (item) {
            var $item = $forms.find('[name$=-' + hiddenField + '][value=' + item[formPK] + ']');
            if ($item.length) {
                var $f = $item.closest(formSelector);
                return {'exists': true, 'visible': $f.is(':visible'), 'item': $f};
            }
        }
        return {'exists': false, 'visible': false};
    }

    function clearInput() {
        $input.val('');
        $input.removeAttr('data-item');
        toggleInput();
    }

    function toggleInput() {
        if (!maxItems) {
            return;
        }
        var $visible = $forms.find(formSelector + ':visible').length;
        if ($visible >= maxItems) {
            $input.prop('disabled', true).slideUp();
            $('.ui-autocomplete').hide();
        } else if ($visible < maxItems) {
            $input.filter(':disabled').prop('disabled', false).slideDown();
        }
    }

    function added() {
        var item = JSON.parse($input.attr('data-item'));

        // Check if this item has already been added.
        var dupe = findItem(item);
        if (dupe.exists) {
            if (!dupe.visible) {
                // Undelete the item.
                var $item = dupe.item;
                $item.find('input[name$=-DELETE]').prop('checked', false);
                $item.slideDown(toggleInput);
            }
            clearInput();
            return;
        }

        clearInput();

        var formId = updateTotalForms(formsetPrefix, 1) - 1,
            emptyForm = $extraForm.html().replace(/__prefix__/g, formId);

        var $f;
        if (addedCB) {
            $f = addedCB(emptyForm, item);
        } else {
            $f = $(f);
        }

        $f.hide().appendTo($forms).slideDown(toggleInput);

        // Update hidden field.
        $forms.find(formSelector + ':last [name$=-' + hiddenField + ']')
              .val(item[formPK]);
    }

    function removed(el) {
        el.slideUp(toggleInput);
        // Mark as deleted.
        el.find('input[name$=-DELETE]').prop('checked', true);

        if (removedCB) {
            removedCB(el);
        }

        // If this was not an initial form (i.e., an extra form), delete the
        // form and decrement the TOTAL_FORMS count.
        if (!el.find('input[name$=-' + formPK + ']').length) {
            el.remove();
            updateTotalForms(formsetPrefix, -1);
        }
    }

    function _renderItem(ul, item) {
        if (!findItem(item).visible) {
            var $a = $(format('<a><img src="{0}" alt="">{1}</a>',
                              [item.icons['32'], _.escape(item.name)]));
            return $('<li>').data('item.autocomplete', item)
                            .append($a).appendTo(ul);
        }
    }

    function _renderItemData(ul, item) {
        var rendered = _renderItem( ul, item );

        // We are overwriting `_renderItem` in some places and return
        // nothing in case of duplicate filtering.
        if (rendered) {
            rendered.data("ui-autocomplete-item", item);
        }
    }

    if (autocomplete) {
        autocomplete();
    } else {
        $input.autocomplete({
            minLength: minLength,
            width: width,
            source: function(request, response) {
                var d = {};
                d[searchField] = request.term;
                $.getJSON(src, d, response);
            },
            focus: function(event, ui) {
                event.preventDefault();
                $input.val(ui.item.name);
            },
            select: function(event, ui) {
                event.preventDefault();
                if (ui.item) {
                    $input.val(ui.item.name);
                    $input.attr('data-item', JSON.stringify(ui.item));
                    added();
                }
            }
        }).data('ui-autocomplete')._renderMenu = function(ul, items) {
            // Overwrite _renderMenu to patch in our custom `_renderItemData`
            // and `_renderItem` to allow for our custom list-filter.
            $.each(items, function(index, item) {
                _renderItemData(ul, item);
            });
        };
    }

    toggleInput();

    $delegate.on('click', '.' + removeClass, _pd(function() {
        removed($(this).closest(formSelector));
    }));

};

})(jQuery);
