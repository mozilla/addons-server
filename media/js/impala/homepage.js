$(function () {
    var promos_base = $('#promos').attr('data-promo-url'),
        promos_url = format('{0}?version={1}&platform={2}', promos_base, z.browserVersion, 'Darwin');
    $.get(promos_url, function(resp) {
        $('#promos ul').append($(resp));
        $('#promos').append('<a href="#" class="control prev">&laquo;</a>\
                             <a href="#" class="control next">&raquo;</a>');
        var $q = $('#promos').zCarousel({
            circular: true,
            btnPrev: $('#promos .prev'),
            btnNext: $('#promos .next')
        });
        $('.vtruncate').truncate({dir: 'v'});
        var interval = setInterval($q.gofwd, 7000);
        $q.hover(function() {
            clearInterval(interval);
        }, function() {
            interval = setInterval($q.gofwd, 7000);
        });
    });
});