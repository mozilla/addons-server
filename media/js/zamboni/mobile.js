$(function() {
    $(window).bind("orientationchange", function(e) {
        $("details").htruncate({textEl: ".desc"});
    });
    $("details").htruncate({textEl: ".desc"});

    $('form.go').change(function() { this.submit(); })
        .find('button').hide();

    $('span.emaillink').each(function() {
        $(this).find('.i').remove();
        var em = $(this).text().split('').reverse().join('');
        $(this).prev('a').attr('href', 'mailto:' + em);
    });
});