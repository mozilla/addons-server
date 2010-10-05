/** Addons Display page */

// note: this overwrites the same object in amo2009/addons.js
var addons_display = {
    /**
     * initialization
     */
    init: function(options) {
        this.options = options;
        $('.rollover-reveal').rolloverReveal({ enable_rollover: false });

        $('#coll_publish button').click(this.coll_publish);
    },

    /**
     * publish an add-on to a collection
     */
    coll_publish: function() {
        var coll_uuid = $('#coll_publish option:selected').val();
        if (!coll_uuid)
            return false;
        else if (coll_uuid == 'new')
            return true;
        var addon_id = $('#coll_publish input[name=\'data[addon_id]\']').val();

        $.post(addons_display.options.jsonURL+'/addon/add', {
                sessionCheck: $('#coll_publish div.hsession>input[name=sessionCheck]').val(),
                collection_uuid: coll_uuid,
                addon_id: addon_id
            },
            function(data) {
                if (data.error) {
                    var msg = $('<div class="error">'+data.error_message+'</div>');
                    $('#coll_publish>button').after(msg);
                    msg.delay(3000, function(){ $(this).fadeRemove(); });
                } else {
                    var coll_uuid = $('#coll_publish option:selected');
                    var msg = $('<div>'
                                +format(gettext('{0} has been added to the {1} collection.'),
                                    [data.name, '<a href="'+addons_display.options.collViewURL
                                                +coll_uuid.val()+'">'+coll_uuid.safeText()+'</a>'])
                                +'</div>');
                    $('#coll_publish button').after(msg);
                    msg.delay(10000, function(){ $(this).fadeRemove(); });
                    coll_uuid.remove();
                }
            }, 'json'
        );
        return false;
    }
}

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

    if ($('#addon.primary').length == 0) return;

    addons_display.init({
        jsonURL: $('#coll_publish').attr('data-json-url'),
        collViewURL: $('#coll_publish').attr('data-detail-url')
    });

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
