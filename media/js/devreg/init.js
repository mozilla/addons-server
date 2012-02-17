var z = {};

$(document).ready(function() {
    // Initialize email links.
    $('span.emaillink').each(function() {
        var $this = $(this);
        $this.find('.i').remove();
        var em = $this.text().split('').reverse().join('');
        $this.prev('a').attr('href', 'mailto:' + em);
    });
    if (z.readonly) {
        $('form[method=post]')
            .before(gettext('This feature is temporarily disabled while we ' +
                            'perform website maintenance. Please check back ' +
                            'a little later.'))
            .find('button, input, select, textarea').attr('disabled', true);
    }
});


function _pd(func) {
    // Prevent-default function wrapper.
    return function(e) {
        e.preventDefault();
        func.apply(this, arguments);
    };
}


function escape_(s) {
    if (typeof s === undefined) {
        return;
    }
    return s.replace(/&/g, '&amp;').replace(/>/g, '&gt;').replace(/</g, '&lt;')
            .replace(/'/g, '&#39;').replace(/"/g, '&#34;');
}


z.anonymous = JSON.parse(document.body.getAttribute('data-anonymous'))
z.media_url = document.body.getAttribute('data-media-url');
z.readonly = JSON.parse(document.body.getAttribute('data-readonly'));
