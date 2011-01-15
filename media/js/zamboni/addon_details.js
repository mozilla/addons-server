/** Addons Display page */

/* general initialization */
$(document).ready(function() {
    //performance warnings
    $(".performance-note .popup").each(function(i,p) {
        var $p = $(p),
            $a = $p.siblings("a").first();
        $p.removeClass("hidden")
          .popup($a, {
            width: 300,
            pointTo: $a
        });
    });

    var abuse = $("fieldset.abuse");
    if (abuse.find("legend a").length) {
        abuse.find("ol").hide();
        abuse.find("legend a").click(function() {
            abuse.find("ol").slideToggle("fast");
            return false;
        });
        abuse.find("button[type=reset]").click(function() {
            abuse.find("ol").slideToggle("fast");
        });
    }

    if ($('#addon.primary').length == 0) return;

    if ($("#addon[data-id]").length) {
        $(".addon .icon").click(function() {
            document.location.hash = "id=" + $("#addon").attr("data-id");
        })
    }

    var lb_baseurl = z.media_url+'img/jquery-lightbox/';
    $("a[rel=jquery-lightbox]").lightBox({
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

    /* No restart required box. (Only shown in Fx4+). */
    var no_restart = $('#addon-summary #no-restart');
    if (no_restart.length && z.browser.firefox
        && (new VersionCompare()).compareVersions(z.browserVersion, '4.0a1') > 0) {
        no_restart.show();
    }
});

/* get satisfaction initialization */
$(document).ready(function () {
    var btn = $('#feedback_btn');
    if (!btn.length) return; // no button, no satisfaction ;)

    var widget_options = {};
    widget_options.display = "overlay";
    widget_options.company = btn.attr('data-company');
    widget_options.placement = "hidden";
    widget_options.color = "#222";
    widget_options.style = "question";
    widget_options.container = 'get_satisfaction_container';
    if (btn.attr('data-product'))
        widget_options.product = btn.attr('data-product');
    var feedback_widget = new GSFN.feedback_widget(widget_options);

    // The feedback widget expects to be right before the end of <body>.
    // Otherwise it's 100% width overlay isn't across the whole page.
    $('#fdbk_overlay').prependTo('body');

    btn.click(function(e) {
        e.preventDefault();
        feedback_widget.show();
    });
});
