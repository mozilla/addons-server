$(document).ready(function() {
    $("#perf-more a").click(function(e) {
        var loc = $(this).attr("href");
        $("#perf-results tr.perf-hidden:lt(5)").removeClass("perf-hidden");
        var $next = $("#perf-results tr.perf-hidden:eq(0)");
        if ($next.length) {
            $(this).attr("href", "#addon-" + $next.attr("data-rank"));
        } else {
            $("#perf-more").remove();
            $("#perf-results table").css("border-bottom-width", 0);
            $("#perf-results tr:last-child").find("td, .impact div")
                                            .css("padding-bottom", 0);
        }
    });
});
