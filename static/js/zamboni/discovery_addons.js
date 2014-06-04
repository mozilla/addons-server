$(document).ready(function(){
    if ($(".detail").length) {
        initDetail();
    }
});


function initDetail() {
    $(".install-action a").attr("target", "_self");

    // Replace with the URL back to the discovery promo pane.
    $("p#back a").attr("href", z.Storage("discopane").get("url"));

    $("#images").fadeIn("slow").addClass("js").zCarousel({
        btnNext: "#images .nav-next a",
        btnPrev: "#images .nav-prev a",
        itemsPerPage: 3
    });
    $(".addon-info").addClass("js");

    // Set up the lightbox.
    var lb_baseurl = z.media_url + "img/jquery-lightbox/";
    $("#images .panel a").lightBox({
        overlayOpacity: 0.6,
        imageBlank: lb_baseurl + "lightbox-blank.gif",
        imageLoading: lb_baseurl + "lightbox-ico-loading.gif",
        imageBtnClose: "",
        imageBtnPrev: "",
        imageBtnNext: "",
        containerResizeSpeed: 350
    });
}
