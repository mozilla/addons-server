/** Addons Display page */

/* general initialization */
$(document).ready(function() {

    // Personas are not impalacized yet!
    if ($("#persona[data-id]").length) {
        $(".addon .icon").click(function() {
            window.location.hash = "id=" + $("#persona").attr("data-id");
        })
    }

    if ($('#addon.primary').length == 0) return;

    var lb_baseurl = z.static_url+'img/jquery-lightbox/';
    $("a[rel='jquery-lightbox']").lightBox({
        overlayOpacity: 0.6,
        imageBlank: lb_baseurl+"lightbox-blank.gif",
        imageLoading: lb_baseurl+"lightbox-ico-loading.gif",
        imageBtnClose: lb_baseurl+"close.png",
        imageBtnPrev: lb_baseurl+"goleft.png",
        imageBtnNext: lb_baseurl+"goright.png",
        containerResizeSpeed: 350
    });

    var etiquette_box = $("#addons-display-review-etiquette").hide();
    $("#short-review").focus(function() { etiquette_box.show("fast"); } );
});
