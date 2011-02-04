$(document).ready(function(){
    $("body").addClass("no-recs");
    initRecs();
    initDescs();
});


function initDescs() {
    // Trim the description text to fit.
    $("p.desc").vtruncate();
    $(window).resize(debounce(function() {
        $("p.desc").vtruncate();
    }, 200));
}


function initRecs() {
    try {
        if (!window.localStorage || !window.JSON || !Object.keys) {
            return;
        }
    } catch(ex) {
        return;
    }

    var services_url = document.body.getAttribute("data-services-url");

    // Where all the current recommendations data is kept.
    var datastore = {};

    // How many add-ons they need to have before we start revealing more.
    var MIN_ADDONS = 3;

    // GUIDs of installed add-ons.
    var guids = [],
        token;
    if (location.hash) {
        guids = Object.keys(JSON.parse(location.hash.slice(1)));
    } else {
        // If the user has opted out of recommendations, clear out any
        // existing recommendations.
        localStorage.removeItem("discopane-recs");
        localStorage.removeItem("discopane-guids");
    }

    function populateRecs() {
        if (datastore.addons.length) {
            var addon_item = template('<li class="panel">' +
                '<a href="{url}" target="_self">' +
                '<img src="{icon}" width="32" height="32">' +
                '<h3>{name}</h3>' +
                '<p class="desc">{summary}</p>' +
                '</a></li>');
            $.each(datastore.addons, function(i, addon) {
                var str = addon_item({
                    url: addon.learnmore,
                    icon: addon.icon,
                    name: addon.name,
                    summary: addon.summary
                });
                $("#recs .slider").append(str);
            });
            $("#recs .gallery").fadeIn("slow").addClass("js").jCarouselLite({
                btnNext: "#recs .nav-next a",
                btnPrev: "#recs .nav-prev a",
                circular: false
            });
            $("#recs #nav-recs").fadeIn("slow").addClass("js");
            setPanelWidth("pane");
            initDescs();
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
    if (guids.length > MIN_ADDONS) {
        $("body").removeClass("no-recs").addClass("recs");

        var cacheObject = localStorage.getItem("discopane-recs");
        if (cacheObject) {
            // Load local data.
            cacheObject = JSON.parse(cacheObject);
            if (cacheObject) {
                datastore = cacheObject;
                token = cacheObject.token;
            }
        }

        // Get new recommendations if there are no saved recommendations or
        // if the user has new installed add-ons.
        var findRecs = !cacheObject;
        var updateRecs = (
            cacheObject &&
            localStorage.getItem("discopane-guids") != guids.toString()
        );
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

            var data = {"guids": guids};
            if (token) {
                data["token"] = token;
            }
            $.ajax({
                url: document.body.getAttribute("data-recs-url"),
                type: "post",
                data: JSON.stringify(data),
                dataType: "text",
                success: function(raw_data) {
                    $("#recs .loading").remove();
                    datastore = JSON.parse(raw_data);
                    populateRecs();
                    localStorage.setItem("discopane-recs", raw_data);
                    localStorage.setItem("discopane-guids", guids);
                }
            });
        } else {
            populateRecs();
        }
    }
}


// Backwards compatibility for the Object.keys method, which was introduced
// in JavaScript 1.8.5 and is supported by FF4.
if (!Object.keys) {
    Object.keys = function(o) {
        var ret = [], p;
        for (p in o) {
            if (Object.prototype.hasOwnProperty.call(o, p)) {
                ret.push(p);
            }
        }
        return ret;
    }
}
