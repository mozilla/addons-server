$(function() {
    if ($('.primary').attr('data-report') != 'overview') return;
    $('.toplist').topChart();
});