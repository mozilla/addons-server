(function () {
    if (!$("#promos").length) return;
    $("#promos").show();
    var promos_base = $('#promos').attr('data-promo-url'),
        promos_url = format('{0}?version={1}&platform={2}', promos_base, z.browserVersion, z.platform);
    $.get(promos_url, function(resp) {
        $('#promos ul').append($(resp));
        $('#promos').append('<a href="#" class="control prev">&laquo;</a>\
                                      <a href="#" class="control next">&raquo;</a>');
        var $q = $('#promos div').zCarousel({
            circular: true,
            btnPrev: $('#promos .prev'),
            btnNext: $('#promos .next')
        });
        $('.vtruncate').truncate({dir: 'v'});
        $('.toplist .name').truncate({showTitle: true});
        $('#promos .install').installButton();
    });
})();