/* Set up the advanced search box. */
z.searchBox = function() {
    if (!$('#search-form').length) return; // no search box

    /* Prevent the placeholder from being submitted as a query. */
    var q = $('#query');
    $('#search-form').submit(function() {
        /* We clicked search, without changing the value. */
        if (q.val() == q.attr('placeholder')) {
            q.val('');
        }
    });

    /* Get the appversions from JSON. */
    var appversions = JSON.parse($('#search-data').attr('data-appversions'));
    for (var k in appversions) {
        appversions[k] = _.dict(appversions[k]);
    }

    /* Replace the <input text> version with a <select>. */
    var lver_parent = $('#id_lver').parent();
    lver_parent.find('input').remove();
    lver_parent.append('<select id="id_lver" name="lver"></select>');

    /* Sync the version <select> with the app id. */
    $('#id_appid').change(function(){
        var app = $('option:selected', this).val();
        /* By default we use 'any', unless there's something set in the url */
        selected = $('#search-data').attr('data-version') || 'any';
        replaceOptions('#id_lver', appversions[app], selected);
    }).change();

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
