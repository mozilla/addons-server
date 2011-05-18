$(function () {
    var promos_url = format('/en-US/firefox/promos/{0}/{1}', z.browserVersion, 'Darwin');
    $.get(promos_url, function(resp) {
        $("#promos ul").append($(resp));
        var $q = $("#promos").zCarousel({
            circular: true
        });
        $('.vtruncate').truncate({dir: 'v'});
        setInterval($q.gofwd, 7000);
    });
});