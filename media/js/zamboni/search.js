/* Set up the advanced search box. */
z.searchBox = function() {
    if (!$('#search-form').length) return; // no search box

     var q = $('#query');

    /* Sync the placeholder text with the category. */
    $('#cat').change(function(){
        var cat = $(this).val(),
            placeholder = gettext('search for add-ons');
        if (cat == 'collections') {
            placeholder = gettext('search for collections');
        } else if (cat == 'personas') {
            placeholder = gettext('search for personas');
        }

        // Update the placeholder and trigger a change.
        q.attr('placeholder', placeholder)
        if (q.hasClass('placeholder')) {
            q.val('').blur();
        }
    }).change();
};
