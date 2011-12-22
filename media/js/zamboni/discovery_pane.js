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
    if ($(".pane").length) {
        initSidebar();

        // Store the pane URL so we can link back from the add-on detail pages.
        z.discoStorage.set("url", location);

        hideInstalled();

        // Show "Starter Pack" panel only if user has fewer than three extensions.
        if (z.has_addons) {
            $("#starter").closest(".panel").remove();
        }

        initRecs();

        // Set up the promo carousel.
        $("#promos").fadeIn("slow").addClass("js").zCarousel({
            btnNext: "#promos .nav-next a",
            btnPrev: "#promos .nav-prev a",
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
    $('.htruncate').truncate({dir: 'h'});
    $('.vtruncate').truncate({dir: 'v'});
    $(window).resize(debounce(function() {
        $('.htruncate').truncate({dir: 'h'});
        $('.vtruncate').truncate({dir: 'v'});
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


// Popcorn Stuff

$(function() {
    if(!location.href.match(/en-US/)) return; // US only!

    var $learn = $('#intro #learn-more'),
        $watch = $('#watch-video'),
        $watch_link = $watch.find('a'),
        $video_close = $('#video-close'),
        $promos = $('#promos'),
        $promo_addons = $('#promo-video-addons');

    // Make the video clean up after itself.
    $video_close.click(_pd(cleanupVideo));
    function cleanupVideo() {
        $learn.text($learn.attr('data-oldtext'));
        $watch_link.text($watch_link.attr('data-oldtext'));
        if ($('#intro').is(':hidden')) {
            $watch.show();
        }
        $('#sub > section').show();
        $promo_addons.hide();
        $('.promo-video, #preload-personas').remove();
        $promos.removeClass('show-video');
    }

    // Load up the locale stuff.
    var translate = {'ja': {'title': 'アドオンとは？',
                            'intro': 'アドオンとは、追加の機能やスタイルで Firefox をカスタマイズ' +
                                     'するアプリケーションのことです。例えば、Web サイトの名前をタ' +
                                     'イプミスしたり、ページがビジー状態で読み込めないときに、ブラ' +
                                     'ウジングをより快適にするためのアドオンがあります。',
                            'featured': '注目のアドオン',
                            'close': '近いビデオ'},
                    'es': {'title': '¿Qué son los complementos?',
                           'intro': 'Los complementos son aplicaciones que te permiten personalizar ' +
                                    'Firefox con funcionalidad y estilos adicionales. Si te equivocas ' +
                                    'al escribir el nombre de un sitio web o no puedes leer una página' +
                                    'ocupada, hay un complemento para mejorar tu navegación.',
                           'featured': 'Complementos destacados',
                           'close': 'Cerrar Vídeo'}};

    // Hijack the learn more button, why don't we?
    if ($('#intro').is(':hidden')) {
        $watch.show();
    }

    $('#intro #learn-more, #watch-video:visible a').show().addClass('video').click(_pd(function() {
        if ($('#main .promo-video:visible').length) {
            cleanupVideo();
            return;
        }

        $learn.attr('data-oldtext', $learn.text());
        $watch_link.attr('data-oldtext', $watch_link.text());
        // English only.
        $learn.text('Close Video');
        $watch_link.text('Close Video');

        // Make #featured-addons able to handle the animations within it
        $('#featured-addons').css('overflow', 'hidden');

        // Let's show the video!
        $promos.addClass('show-video');
        var video = $('<div>', {'class': 'promo-video'});
        var video_el = $('<video>', {'controls': 'controls', 'tabindex': 0, 'id': 'promo-video', 'text': gettext('Your browser does not support the video tag')});
        var video_el_mp4  = $('<source>', {'type': 'video/mp4; codecs="avc1.42E01E, mp4a.40.2"', 'src': 'https://static.addons.mozilla.net/media/videos/fds0fo.mov'});
        var video_el_webm = $('<source>', {'type': 'video/webm; codecs="vp8, vorbis"', 'src': 'https://static.addons.mozilla.net/media/videos/vuue2y.webm'});
        var video_el_ogv = $('<source>', {'type': 'video/ogv; codecs="theora, vorbis";', 'src': 'https://static.addons.mozilla.net/media/videos/b85p03.ogv'});
        var $video_details = $('#video-details');

        video_el.append(video_el_mp4);
        video_el.append(video_el_webm);
        video_el.append(video_el_ogv);
        video.append(video_el);

        $promos.append(video);

        // Preload persona images
        var preload = $('<div>', {'id': 'preload-personas', 'css': {'display': 'none'}}).appendTo('body');
        $promo_addons.find('a[data-browsertheme]').each(function() {
            var theme = $.parseJSON($(this).attr('data-browsertheme'));
            preload.append($('<img>', {'src': theme['headerURL']}));
            preload.append($('<img>', {'src': theme['footerURL']}));
        });

        // Move some stuff around
        $('#sub > section').hide();
        $promo_addons.fadeIn();

        // If we don't have the "What Are Add-ons?" banner, we show the
        // "Learn More"/"Close Video" button above the add-ons list, so this
        // gets rid of the redundant one below.
        if ($watch_link.is(':visible')) {
            $video_close.remove();
        }

        // Set up Popcorn
        var pop = Popcorn('#promo-video'),
            $addons = $promo_addons.find('ul li'),
            $toFlash = $('#promo-video-addons, header, #featured-addons'),
            $featured = $('#featured-addons li'),
            $trans = $('.translate');

        // Save the original translation text
        $trans.each(function() {
            $this = $(this);
            $this.attr('data-original', $this.text());
        });

        // The actions
        showAddon(0, 20, 24.5);
        showAddon(1, 24.5, 26.5);
        showAddon(2, 26.5, 29.5);
        showAddon(3, 32);
        showFlash(33.5, 34.7);
        showFlash(34.7, 36);
        showAddon(4, 37);
        showAddon(5, 40);
        showFlutter(48, 56);
        showAddon(6, 53);
        showDrop(54.8, 56);
        showAddon(7, 57);
        showTrans('ja', 59, 59.8);
        showTrans('es', 59.8, 60.8);

         // Play the video after one second.
         setTimeout(function() {
             pop.play();
         }, 1000);

        // The action functions
        function showAddon(i, time, end) {
            var addon = $addons.eq(i),
                $addon_a = addon.find('a');
            pop.code({
                start: time,
                end: 100000,
                onStart: function() {
                    $video_details.hide();
                    addon.addClass('show');
                    $addons.removeClass('last');
                    // So we can do a nice border-radius on the last visible.
                    $addons.filter(':visible:last').addClass('last');
                },
                onEnd: function() {
                    addon.removeClass('show');
                    if($addons.filter('.show').length == 0) {
                        $video_details.show();
                    }
                }
            });

            if($addon_a.attr('data-browsertheme')) {
                pop.code({
                    start: time,
                    end: end,
                    onStart: function() {
                        dispatchPersonaEvent('PreviewPersona', $addon_a[0]);
                    },
                    onEnd: function() {
                        dispatchPersonaEvent('ResetPersona', $addon_a[0]);
                    }
                });
            }
        }

        function showFlash(start, end) {
            pop.code({
                start: start,
                end: end,
                onStart: function() {
                    $toFlash.css({'opacity': 0}).animate({'opacity': 1});
                }
            });
        }

        function showFlutter(start, end) {
            pop.code({
                start: start,
                end: end,
                onStart: function() {
                    // Only do this if we can see the featured add-ons
                    if($(window).scrollTop() + $(window).height() > $('#featured-addons').position()['top'] + 80) {
                        $featured.each(function() {
                            var $this = $(this);

                            setTimeout(function() {
                                $this.addClass('flutter');
                            }, 300 * Math.random());

                            setTimeout(function() {
                                $this.animate({'top': 400, 'left': -400}, function() {
                                    $this.removeClass('flutter');
                                });
                            }, 3000 * Math.random());
                        });
                    }
                },
                onEnd: function() {
                    $featured.css({'top': 0, 'left': 0}).removeClass('flutter');
                }
            });
        }

        function showDrop(start, end) {
            pop.code({
                start: start,
                end: end,
                onStart: function() {
                    $featured.removeClass('flutter').css({'top': -400, 'left': 0}).animate({'top': 0});
                }
            });
        }

        function showTrans(locale, start, end) {
            pop.code({
                start: start,
                end: end,
                onStart: function() {
                    $trans.each(function() {
                        var $this = $(this);
                        $this.text(translate[locale][$this.attr('data-trans')]);
                    });
                },
                onEnd: function() {
                    $trans.each(function() {
                        var $this = $(this);
                        $this.text($this.attr('data-original'));
                    });
                }
            });
        }
    }));

    $watch.click(_pd(function(){
        $('body, html').animate({'scrollTop': 0});
    }));
});
