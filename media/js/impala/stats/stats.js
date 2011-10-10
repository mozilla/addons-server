$(function() {
    var initView = {
            metric: $('.primary').attr('data-report'),
            range: '365 days', //$('.primary').attr('data-range'),
            group: 'month'
        };

    $(window).trigger('changeview', initView);
});

$(window).bind("changeview", function(e, view) {
    var queryParams;
    if (view.range) {
        if (typeof view == "string") {
            queryparams = "last=" + view.split(/\s+/)[0];
            history.replaceState(view, document.title, '?' + queryparams);
        } else if (typeof view == "object") {
            
        }
    }
})