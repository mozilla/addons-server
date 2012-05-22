function ratingHistory(el, history) {
    // init to win it
    el.width = el.offsetWidth;
    el.height = el.offsetHeight;
    var ctx = el.getContext('2d'),
        size = el.height / 2,
        i, row, x, y;

    // normalize values
    var max = 0;
    for (i=0; i<history.length; i++) {
        max = Math.max(max, history[i][0], history[i][1]);
    }
    var yscale = (size / max),
        xscale = (el.width / history.length),
        cpx = xscale / 2;

    // positive ratings
    ctx.fillStyle = 'rgba(0, 200, 0, .2)';
    ctx.strokeStyle = 'green';
    plotSeries(0, -1);

    // negative ratings
    ctx.fillStyle = 'rgba(200, 0, 0, .2)';
    ctx.strokeStyle = 'red';
    plotSeries(1, 1);

    function plotSeries(idx, dir) {
        ctx.beginPath();
        // start outside viewport to hide stroke
        ctx.moveTo(-2, size);
        ox = 0;
        oy = size + history[0][idx] * yscale * dir;
        ctx.lineTo(-2, oy);
        ctx.lineTo(0, oy);
        for (i=1; i<history.length; i++) {
            row = history[i];
            x = i * xscale + xscale;
            y = size + row[idx] * yscale * dir;
            ctx.bezierCurveTo(x-cpx, oy, ox+cpx, y, x, y);
            oy = y;
            ox = x;
        }
        // finish outside viewport to hide stroke
        ctx.lineTo(ox+2, oy);
        ctx.lineTo(ox+2, size);
        ctx.fill();
        ctx.stroke();
    }
}

(function() {
    z.page.on('fragmentloaded', function() {
        var $reviewEl = $('#reviews'),
            data = $reviewEl.data('review-history');
        if ($reviewEl.exists() && data) {
            $reviewEl.find('div:first-child')
                     .prepend('<figure><figcaption>Reviews, last 30 days</figcaption>' +
                              '<canvas id="review-spark"></canvas></figure>');
            ratingHistory($('#review-spark')[0], data);
        }
    });
})();

z.page.on('click', '[data-review-filter]', function(e) {
    e.preventDefault();
    var filter = $(this).data('review-filter');
    $('#review-list').removeClass('filter-positive filter-negative filter-all');
    $('#review-list').addClass('filter-' + filter);
    $('[data-review-filter]').removeClass('selected');
    $(this).addClass('selected');

});