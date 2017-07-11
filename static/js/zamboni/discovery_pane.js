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

    initPromos(null, 'discovery');
    $(this).on('promos_shown', function(e, $promos) {
        if($('#learn-more').hasClass('video')) { // Is the video available?
            var starter = $('#starter').closest('.panel'),
            s_panel = $('<li>', {'class': 'panel'}),
            s_div = $('<div>', {'class': 'feature promo', 'id': 'addon-video-promo'}),
            s_title = $('<h2>', {'text': 'First time with Add-ons?'}),
            s_sub = $('<h3>', {'text': 'Check out our interactive video to learn about some of the awesome things you can do with add-ons!'}),
            s_button = $('<a>', {'html': '<strong>Watch</strong> the Video', 'href': '#'}),
            s_button_span = $('<span>', {'class': 'vid-button view-button'}),
            s_guy = $('<div>', {'class': 'vid-guy'});

            starter.replaceWith(s_panel);
            s_panel.append(s_div);
            s_div.append(s_title);
            s_div.append(s_sub);
            s_button_span.append(s_button);
            s_div.append(s_button_span);
            s_div.append(s_guy);
        } else if (z.has_addons) {
            // Show "Starter Pack" panel only if user has fewer than 3 extensions.
            $('#starter').closest('.panel').remove();
        }
        // Set up the promo carousel.
        $promos.fadeIn('slow').addClass('js').zCarousel({
            btnNext: '#promos .nav-next a',
            btnPrev: '#promos .nav-prev a',
            circular: true
        });

        // Intialize the pager for any paging promos
        $('.pager', $promos).promoPager();

        initTrunc();
        // Initialize install button.
        $('.install', $promos).installButton();
        var $disabled = $('.disabled, .concealed', $promos);
        if ($disabled.length) {
            $disabled.closest('.wrap').addClass('hide-install');
        }
    });
});


function getGuids() {
    // Store GUIDs of installed extensions.
    var guids = [];
    if (location.hash) {
        $.each(JSON.parse(unescape(location.hash).slice(1)), function(i, val) {
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
    $('.ryff .desc').lineclamp(6);
    $('#promos h2:not(.multiline)').linefit();
    $(window).resize(debounce(function() {
        $('.htruncate').truncate({dir: 'h'});
        $('.vtruncate').truncate({dir: 'v'});
        $('#promos h2:not(.multiline)').linefit();
    }, 200));
}


function initSidebar() {
    var account_url = document.body.getAttribute("data-account-url");
    $.get(account_url, function(data) {
        var trimmed_data = data.trim();
        if ($(trimmed_data).find("#my-account").length) {
            $("header").addClass("auth");
        }
        $("#right-module").replaceWith(trimmed_data).slideDown("slow");
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
                if ($.trim(data)) {
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
                }
            });
        }
    }

    fillSpots($('#featured-addons ul'), z.MAX_FEATURED,
              document.body.getAttribute('data-featured-url'));
    fillSpots($('#up-and-coming ul'), z.MAX_UPANDCOMING,
              document.body.getAttribute('data-upandcoming-url'));
}
