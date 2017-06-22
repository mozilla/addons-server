// Popcorn Stuff

function PopcornObj() {
    var $learn = $('#intro #learn-more'),
        $watch = $('#watch-video'),
        $watch_link = $watch.find('a'),
        $video_close = $('#video-close'),
        $promos = $('#promos'),
        $promo_addons = $('#promo-video-addons'),
        $addons = $promo_addons.find('ul li'),
        $toFlash = $('#promo-video-addons, header, #featured-addons'),
        $featured = $('#featured-addons li'),
        $trans = $('.translate'),
        pop = false;

    var video, video_el, video_el_mp4, video_el_webm, video_el_ogv, $video_details;

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

    var p = this;

    this.init = function() {
        // If we don't have the "What Are Add-ons?" banner, we show the
        // "Learn More"/"Close Video" button above the add-ons list, so this
        // gets rid of the redundant one below.
        if ($watch_link.is(':visible')) {
            $video_close.remove();
        }

        if ($('#intro').is(':hidden')) {
            $watch.show();
        }
    }
    this.init();

    this.start = function() {
        if(video) { // Video has already been created
            video.show();
            $promos.addClass('show-video');
            pop.currentTime(0).play();
        } else {
            $promos.addClass('show-video');
            video = $('<div>', {'class': 'promo-video'});
            video_el = $('<video>', {'controls': 'controls', 'tabindex': 0, 'id': 'promo-video', 'text': 'Your browser does not support the video tag'});
            video_el_mp4  = $('<source>', {'type': 'video/mp4; codecs="avc1.42E01E, mp4a.40.2"', 'src': 'https://videos.cdn.mozilla.net/addons/fds0fo.mov'});
            video_el_webm = $('<source>', {'type': 'video/webm; codecs="vp8, vorbis"', 'src': 'https://videos.cdn.mozilla.net/addons/vuue2y.webm'});
            video_el_ogv = $('<source>', {'type': 'video/ogg; codecs="theora, vorbis"', 'src': 'https://videos.cdn.mozilla.net/addons/b85p03.ogv'});
            $video_details = $('#video-details');

            video_el.append(video_el_mp4, video_el_webm, video_el_ogv);
            video.append(video_el);

            $promos.append(video);

            // Preload persona images
            var preload = $('<div>', {'id': 'preload-personas', 'css': {'display': 'none'}}).appendTo('body');
            $promo_addons.find('a[data-browsertheme]').each(function() {
                var theme = parse.JSON($(this).attr('data-browsertheme'));
                preload.append($('<img>', {'src': theme['headerURL'].replace(/http:\/\//, 'https://'), 'alt': ''}));
                preload.append($('<img>', {'src': theme['footerURL'].replace(/http:\/\//, 'https://'), 'alt': ''}));
            });

            // Save the original translation text
            $trans.each(function() {
                var $this = $(this);
                $this.attr('data-original', $this.text());
            });

            pop = Popcorn('#promo-video');

            p.showAddon(0, 20, 24.5);
            p.showAddon(1, 24.5, 26.5);
            p.showAddon(2, 26.5, 29.5);
            p.showAddon(3, 32);
            p.showFlash(33.5, 34.7);
            p.showFlash(34.7, 36);
            p.showAddon(4, 37);
            p.showAddon(5, 40);
            p.showFlutter(48, 56);
            p.showAddon(6, 53);
            p.showDrop(54.8, 56);
            p.showAddon(7, 57);
            p.showTrans('ja', 59, 59.8);
            p.showTrans('es', 59.8, 60.8);
        }

        // Move some stuff around.
        $('#sub > section').hide();
        $promo_addons.fadeIn();

        // Scroll to the top of the page!
        $watch.click(_pd(function(){
            $('body, html').animate({'scrollTop': 0});
        }));

        // Create a close button
        this.setup_close_button();

        /* Andddd go! */
        pop.play();
    };

    this.setup_close_button = function() {
        $learn.attr('data-oldtext', $learn.text());
        $watch_link.attr('data-oldtext', $watch_link.text());
        $learn.add($watch_link).addClass('close').text('Close Video'); // English only, so we're good.

        $video_close.click(_pd(function(){ p.stop(); }));
    };

    this.stop = function(e) {
        if(pop) {
            pop.pause();
        }
        $('#promo-video').trigger('close');
        $learn.text($learn.attr('data-oldtext'));
        $watch_link.text($watch_link.attr('data-oldtext'));

        $learn.add($watch_link).removeClass('close');

        $('#sub > section').show();
        $promo_addons.hide();
        if(video) {
            video.hide();
        }
        $promos.removeClass('show-video');
    };

    this.code = function(options){
        if(options['onEnd']) {
            $('#promo-video').on('close', options['onEnd']);
        }
        pop.code(options);
    }

    this.showAddon = function(i, time, end) {
        var addon = $addons.eq(i),
            $addon_a = addon.find('a');

        p.code({
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

        // Personas!
        if($addon_a.attr('data-browsertheme')) {
            p.code({
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

    this.showFlash = function(start, end) {
        p.code({
            start: start,
            end: end,
            onStart: function() {
                $toFlash.css('opacity', 0).animate({'opacity': 1});
            }
        });
    }

    this.showFlutter = function(start, end) {
        p.code({
            start: start,
            end: end,
            onStart: function() {
                // Only do this if we can see the featured add-ons
                var $window = $(window);
                if($window.scrollTop() + $window.height() > $('#featured-addons').position()['top'] + 80) {
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

    this.showDrop = function(start, end) {
        p.code({
            start: start,
            end: end,
            onStart: function() {
                $featured.removeClass('flutter').css({'top': -400, 'left': 0}).animate({'top': 0});
            }
        });
    }

    this.showTrans = function(locale, start, end) {
        p.code({
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
};

$(function() {
    var popcorn = new PopcornObj();
    $('#intro #learn-more, #watch-video:visible a').show().addClass('video').click(_pd(function() {
        if($(this).hasClass('close')) return popcorn.stop();
        popcorn.start();
    }));

    $('#promos').on('click', '.vid-button a', _pd(function() {
        popcorn.start();
    }));
});
