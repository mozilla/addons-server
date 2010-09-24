$(document).ready(function() {
    $("#contribute-why").popup("#contribute-more-info", {
        pointTo: "#contribute-more-info"
    });

    $('canvas.pledge-o-meter').thermometer();
});
