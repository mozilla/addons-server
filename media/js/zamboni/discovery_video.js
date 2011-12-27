// Popcorn Stuff

$(function() {
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
            preload.append($('<img>', {'src': theme['headerURL'].replace(/http:\/\//, 'https://')}));
            preload.append($('<img>', {'src': theme['footerURL'].replace(/http:\/\//, 'https://')}));
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
                        dispatchPersonaEvent('PreviewPersona', $addon_a[0], false, true);
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
