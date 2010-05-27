/* Set up the advanced search box. */
z.searchBox = function() {
    if (!$('#search-form').length) return; // no search box

    var disable_inputs = function() {
        $('#advanced-search select:not(#id_pp)').attr('disabled', 'disabled');
    }

    /* Sync the placeholder text with the category. */
    $('#cat').change(function(){
        var cat = $(this).val();
        var placeholder;

        if (cat == 'collections') {
            placeholder = gettext('search for collections');
            disable_inputs();
        } else if (cat == 'personas') {
            placeholder = gettext('search for personas');
            disable_inputs();
        } else {
            placeholder = gettext('search for add-ons');
            $('#advanced-search select').attr('disabled', '');
        }

        $('#query').placeholder(placeholder);

    }).change();
};
