$(function () {
    var promos_base = $('#promos').attr('data-promo-url'),
        promos_url = format('{0}?version={1}&platform={2}', promos_base, z.browserVersion, 'Darwin');
    $.get(promos_url, function(resp) {
        $("#promos ul").append($(resp));
        var $q = $("#promos").zCarousel({
            circular: true
        });
        $('.vtruncate').truncate({dir: 'v'});
        $q.click($q.gofwd);
    });
});