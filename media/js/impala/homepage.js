(function () {
    if (!$("#promos").length) return;
    $("#promos").show();
    var promos_base = $('#promos').attr('data-promo-url'),
        promos_url = format('{0}?version={1}&platform={2}', promos_base, z.browserVersion, z.platform);
    if (z.badBrowser) {
        promos_url = format('{0}?version={1}&platform={2}', promos_base, '5.0', 'mac');
    }
    $.get(promos_url, function(resp) {
        $('#promos ul').append($(resp));
        $('#promos').append('<a href="#" class="control prev">&laquo;</a>\
                                      <a href="#" class="control next">&raquo;</a>');
        var $q = $('#promos div').zCarousel({
            circular: true,
            btnPrev: $('#promos .prev'),
            btnNext: $('#promos .next')
        });
        $('#promos .addons h3').truncate({dir: 'h'});
        $('#promos .addons .desc').truncate({dir: 'v'});
        $('#promos .install').installButton();
    });
    $('.toplist .name').truncate({showTitle: true});
})();