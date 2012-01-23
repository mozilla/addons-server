// Minimum number of installed extensions, used for toggling user
// recommendations and "Starter Pack" promo pane.
z.MIN_EXTENSIONS = 3;

// Number of Featured Add-ons.
z.MAX_FEATURED = 6;

// Number of Up & Coming Add-ons.
z.MAX_UPANDCOMING = 5;

// Parse GUIDS of installed extensions from JSON fragment.
z.guids = getGuids();
z.has_addons = z.guids.length >= z.MIN_EXTENSIONS;

z.discoStorage = z.Storage("discopane");


$(document).ready(function(){
    if (!$('.pane').length) {
        return;
    }

    initSidebar();
    // Store the pane URL so we can link back from the add-on detail pages.
    z.discoStorage.set('url', location);
    hideInstalled();
    initRecs();

    var $body = $(document.body);
    initPromos($body, $body.attr('data-version'), $body.attr('data-platform'),
               'discovery');
    $(this).bind('promos_shown', function(e, $promos) {
        // Show "Starter Pack" panel only if user has fewer than 3 extensions.
        if (z.has_addons) {
            $('#starter').closest('.panel').remove();
        }
        // Set up the promo carousel.
        $promos.fadeIn('slow').addClass('js').zCarousel({
            btnNext: '#promos .nav-next a',
            btnPrev: '#promos .nav-prev a',
            circular: true
        });
        initTrunc();
    });
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
    $('.htruncate').truncate({dir: 'h'});
    $('.vtruncate').truncate({dir: 'v'});
    $('#monthly .blurb > p').lineclamp(4);
    $('#promos h2').linefit();
    $(window).resize(debounce(function() {
        $('.htruncate').truncate({dir: 'h'});
        $('.vtruncate').truncate({dir: 'v'});
        $('#promos h2').linefit();
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
}


function hideInstalled() {
    // Do not show installed extensions in the promo modules or sidebar.
    $.each(z.guids, function(i, val) {
        var $el = $(format('li[data-guid="{0}"]', [val]));
        if ($el.length && $el.siblings().length) {
            $el.remove();
        }
    });

    // Get more add-ons so we can fill the vacant spots.
    function fillSpots(ul, minSpots, url) {
        var numListed = ul.find('li').length;
        if (numListed < minSpots) {
            var emptySpots = minSpots - numListed;
            $.get(url, function(data) {
                $.each($(data).find('li'), function() {
                    var $el = $(this),
                        guid = $el.attr('data-guid');
                    // Ensure that the add-on isn't already in the list and
                    // that it's not already installed by the user.
                    if (!ul.find(format('li[data-guid="{0}"]', [guid])).length &&
                        $.inArray(guid, z.guids) === -1) {
                        ul.append($el);
                        // We're done if all spots have been filled.
                        if (emptySpots-- == 1) {
                            return false;
                        }
                    }
                });
                initTrunc();
            });
        }
    }

    fillSpots($('#featured-addons ul'), z.MAX_FEATURED,
              document.body.getAttribute('data-featured-url'));
    fillSpots($('#up-and-coming ul'), z.MAX_UPANDCOMING,
              document.body.getAttribute('data-upandcoming-url'));
}


function initRecs() {
    var showRecs = JSON.parse(document.body.getAttribute("data-show-recs"));
    // Where all the current recommendations data is kept.
    var datastore = {};

    var token2;

    if (!location.hash || !z.guids.length) {
        // If the user has opted out of recommendations, clear out any
        // existing recommendations.
        z.discoStorage.remove("recs");
        z.discoStorage.remove("guids");
    }

    function populateRecs() {
        if (datastore.addons !== undefined && datastore.addons.length) {
            var addon_item = template('<li class="panel addon-feature">' +
                '<a href="{url}" target="_self">' +
                '<img src="{icon}" width="32" height="32">' +
                '<h3 class="htruncate">{name}</h3>' +
                '<p class="desc vtruncate">{summary}</p>' +
                '</a></li>');
            var persona_item = template('<li class="panel persona-feature">' +
                '<a href="{url}" target="_self">' +
                '<h3 class="htruncate">{name}</h3>' +
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
                itemsPerPage: 3,
                prop: "left"  // LTR looks better even for RTL.
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

        var cacheObject = z.discoStorage.get("recs");
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
        var updateRecs = cacheObject && z.discoStorage.get("guids") != z.guids.toString();
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
                    z.discoStorage.set("updated", new Date());
                    z.discoStorage.set("recs", raw_data);
                    z.discoStorage.set("guids", z.guids);
                },
                error: function(raw_data) {
                    $("#recs .loading").remove();
                    populateRecs();
                }
            });
        } else {
            populateRecs();
        }
    }
}
