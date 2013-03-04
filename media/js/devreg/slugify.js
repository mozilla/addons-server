// Slugify
// This allows you to create a line of text with a "Edit" field,
// and swap it out for an editable slug.  For example:
//
// http://mozilla.com/slugname <a>edit</a>
// ..to..
// http://mozilla.com/[editable slug name]

function load_unicode() {
    var $body = $(document.body);
    $body.append("<script src='" + $body.attr('data-media-url') + "/js/zamboni/unicode.js'></script>");
}

function makeslug(s, delimiter) {
    if (!s) return "";
    var re = new RegExp("[^\\w" + z.unicode_letters + "\\s-]+","g");
    s = $.trim(s.replace(re, ' '));
    s = s.replace(/[-\s]+/g, delimiter || '-').toLowerCase();
    return s;
}

function show_slug_edit(e) {
    $("#slug_readonly").hide();
    $("#slug_edit").show();
    $("#id_slug").focus();
    e.preventDefault();
}

function slugify() {
    if (z == null || z.unicode_letters) {
        var slug = $('#id_slug');
        url_customized = slug.attr('data-customized') == 0 ||
                                   !slug.attr('data-customized');
        if (url_customized || !slug.val()) {
            var s = makeslug($('#id_name').val());
            slug.val(s);
            name_val = s;
            $('#slug_value').text(s);
        } else {
            $('#slug_value').text($('#id_slug').val());
        }
    } else {
        load_unicode();
    }
}

