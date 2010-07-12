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

/* Add to collection initialization */
$(document).ready(function () {
    var btn = $('.collection-add');
    var dropdown = $('.collection-add-dropdown');
    if (!btn.length) return;

    btn.show();

    var refreshHandlers = function() {
        $('#collections-new button').click(handleSubmit);
        $('#ajax_collections_list li').click(handleToggle);
        $('#ajax_new_collection').click(handleNew);
        $('#collections-new-cancel').click(handleClick);
    };

    var list_url = btn.attr('data-listurl');
    var remove_url = btn.attr('data-removeurl');
    var add_url = btn.attr('data-addurl');
    var form_url = btn.attr('data-newurl');
    var addon_id = $('#addon').attr('data-id');

    var handleToggle = function() {
        var data = {'addon_id': addon_id,
                    'id': this.getAttribute('data-id')};
        var url = this.className == "selected" ? remove_url
                                               : add_url;
        $.post(url, data, handleClick);
    }

    var handleSubmit = function(e) {
        e.preventDefault()
        form_data = $('#collections-new form').serialize();
        $.post(form_url + '?addon_id=' + addon_id, form_data, function(d) {
            dropdown.html(d);
            refreshHandlers();
        });
    }

    var handleNew = function(e) {
        $.get(form_url, {'addon_id': addon_id}, function(d) {
            dropdown.html(d);
            refreshHandlers();
        });
    }

    var handleClick = function(e) {
        // If anonymous, show login overlay.
        dropdown.show();
        // Make a call to /collections/ajax/list with addon_id
        if (!z.anonymous) {
            $.get(list_url, {'addon_id': addon_id}, function(data) {
                dropdown.html(data);
                refreshHandlers();
            }, 'html');
        }
    };
    btn.click(handleClick);



});
