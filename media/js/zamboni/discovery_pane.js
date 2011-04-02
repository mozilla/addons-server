// Minimum number of installed extensions, used for toggling user
// recommendations and "Starter Pack" promo pane.
z.MIN_EXTENSIONS = 3;

// Parse GUIDS of installed extensions from JSON fragment.
z.guids = getGuids();


$(document).ready(function(){
    if ($(".pane").length) {
        initSidebar();

        // Store the pane URL so we can link back from the add-on detail pages.
        Storage.set("discopane-url", location);

        // Show "Starter Pack" panel only if user has fewer than three extensions.
        if (z.guids.length >= z.MIN_EXTENSIONS) {
            $("#starter").closest(".panel").remove();
        }

        initRecs();

        // Set up the promo carousel.
        $("#main-feature").fadeIn("slow").addClass("js").zCarousel({
            btnNext: "#main-feature .nav-next a",
            btnPrev: "#main-feature .nav-prev a",
            circular: true
        });

        initTrunc();
    }
});


function getGuids() {
    // Store GUIDs of installed extensions.
    var guids = [];
    if (location.hash) {
        $.each(JSON.parse(location.hash.slice(1)), function(i, val) {
            if (val.type == "extension") {
                guids.push(i);
            }
        });
    }
    return guids;
}


function initTrunc() {
    // Trim the add-on title and description text to fit.
    $(".addons h3, .rec-addons h3, p.desc").truncate({dir: 'v'});
    $(window).resize(debounce(function() {
        $(".addons h3 a, .rec-addons h3 a, p.desc").truncate({dir: 'v'});
    }, 200));
}


function initSidebar() {
    var account_url = document.body.getAttribute("data-account-url");
    $.get(account_url, function(data) {
        if ($(data).find("#my-account").length) {
            $("header").addClass("auth");
        }
        $("#right-module").replaceWith(data).slideDown("slow");
    });

    $('li[data-guid]').each(function() {
        var $el = $(this),
            guid = $el.attr('data-guid');
        if ($el.siblings().length > 1) {
            for (key in z.guids) {
                if (z.guids[key] == guid) {
                    $el.remove();
                    break;
                }
            }
        }
    });
}


function initRecs() {
    var showRecs = JSON.parse(document.body.getAttribute("data-show-recs"));
    // Where all the current recommendations data is kept.
    var datastore = {};

    var token2;

    if (!location.hash || !z.guids.length) {
        // If the user has opted out of recommendations, clear out any
        // existing recommendations.
        Storage.remove("discopane-recs");
        Storage.remove("discopane-guids");
    }

    function populateRecs() {
        if (datastore.addons !== undefined && datastore.addons.length) {
            var addon_item = template('<li class="panel addon-feature">' +
                '<a href="{url}" target="_self">' +
                '<img src="{icon}" width="32" height="32">' +
                '<h3>{name}</h3>' +
                '<p class="desc">{summary}</p>' +
                '</a></li>');
            var persona_item = template('<li class="panel persona-feature">' +
                '<a href="{url}" target="_self">' +
                '<h3>{name}</h3>' +
                '<div class="persona persona-large">' +
                '<div class="persona-inner">' +
                '<div class="persona-preview">' +
                '<div data-browsertheme="" style="background-image:url({preview})"></div>' +
                '</div></div></div>' +
                '</a></li>');

            $.each(datastore.addons, function(i, addon) {
                var li;
                if (addon.type == 'persona') {
                    li = persona_item({
                        url: addon.learnmore,
                        name: addon.name,
                        preview: addon.previews[0]
                    });
                } else {
                    li = addon_item({
                        url: addon.learnmore,
                        icon: addon.icon,
                        name: addon.name,
                        summary: $("<span>" + (addon.summary != null ? addon.summary : "") + "</span>").text()
                    });
                }
                $("#recs .slider").append(li);
            });
            $("#recs .gallery").fadeIn("slow").addClass("js").zCarousel({
                btnNext: "#recs .nav-next a",
                btnPrev: "#recs .nav-prev a",
                itemsPerPage: 3
            });
            $("#recs #nav-recs").fadeIn("slow").addClass("js");
            initTrunc();
            $("#recs .persona-preview").previewPersona(true);
        } else {
            var addons_url = $("#more-addons a").attr("href");
            var msg = format(gettext(
                "Sorry, we couldn't find any recommendations for you.<br>" +
                'Please visit the <a href="{0}">add-ons site</a> to ' +
                "find an add-on that's right for you."), [addons_url]);
            $("#recs .gallery").hide();
            $("#recs").append('<div class="msg"><p>' + msg + "</p></div>");
        }
    }

    // Hide "What are Add-ons?" and show "Recommended for You" module.
    if (showRecs && z.guids.length > z.MIN_EXTENSIONS) {
        $("body").removeClass("no-recs").addClass("recs");

        var cacheObject = Storage.get("discopane-recs");
        if (cacheObject) {
            // Load local data.
            cacheObject = JSON.parse(cacheObject);
            if (cacheObject) {
                datastore = cacheObject;
                token2 = cacheObject.token2;
            }
        }

        // Get new recommendations if there are no saved recommendations or
        // if the user has new installed add-ons.
        var findRecs = !cacheObject;
        var updateRecs = cacheObject && Storage.get("discopane-guids") != z.guids.toString();
        if (findRecs || updateRecs) {
            var msg;
            if (findRecs) {
                msg = gettext("Finding recommendations&hellip;");
            } else if (updateRecs) {
                msg = gettext("Updating recommendations&hellip;");
            }
            $("#recs .gallery").hide();
            $("#recs").append('<div class="msg loading"><p><span></span>' +
                              msg + "</p></div>");

            var data = {"guids": z.guids};
            if (token2) {
                data["token2"] = token2;
            }
            datastore = {};
            $.ajax({
                url: document.body.getAttribute("data-recs-url"),
                type: "post",
                data: JSON.stringify(data),
                dataType: "text",
                success: function(raw_data) {
                    $("#recs .loading").remove();
                    datastore = JSON.parse(raw_data);
                    populateRecs();
                    Storage.set("discopane-updated", new Date());
                    Storage.set("discopane-recs", raw_data);
                    Storage.set("discopane-guids", z.guids);
                },
                error: function(raw_data) {
                    $("#recs .loading").remove();
                    populateRecs();
                    Storage.remove("discopane-recs");
                    Storage.remove("discopane-guids");
                }
            });
        } else {
            populateRecs();
        }
    }
}
