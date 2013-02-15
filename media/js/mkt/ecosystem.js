(function() {
    var videos = $('.videos');
    var videoItems = videos.find('.video-item');
    var videoObjects = videos.find('video');
    var videoThumbs = videos.find('.video-thumbs');
    var appScreenshots = $('#screenshots');
    var currentScreenshot = $('.current-screenshot');
    var appGeneratorPreviews = $('.app-generator-preview');
    var appGeneratorDetail = $('.app-generator-detail');
    var appGeneratorItems = appGeneratorDetail.find('> li');
    var sideNav = $('#document-navigation');

    // Video functions taken from https://github.com/mozilla/bedrock/blob/master/media/js/marketplace/partners.js
    var getNewObject = function(vidObject)
    {
        var data = $object.attr('data');
        data = data.replace(/&/g, '&amp;');
        var html =
              '<object '
            + 'type="application/x-shockwave-flash" '
            + 'style="width: 509px; height: 278px;" '
            + 'data="' + data + '">'
            + '<param name="movie" value="' + data + '" />'
            + '<param name="wmode" value="transparent" />'
            + '<div class="video-player-no-flash">'
            + gettext('This video requires a browser with support for open video ')
            + gettext('or the <a href="http://www.adobe.com/go/getflashplayer">Adobe ')
            + gettext('Flash Player</a>.')
            + '</div>'
            + '</object>';

        return $(html);
    };

    var stopVideos = function() {
        var el;

        for (var i = 0; i < videoObjects.length; i ++) {
            el = videoObjects[i];
            if (typeof HTMLMediaElement !== 'undefined') {
                el.pause();
                el.currentTime = 0;
                if (el._control) {
                    el._control.show();
                }
            } else {
                // Delete and re-add Flash object. We don't have the
                // documentation to script it :-(
                (function() {
                    var theEl = el;
                    var vidObject = $('object', theEl);
                    var newObject = getNewObject(vidObject);
                    setTimeout(function() {
                        vidObject.remove();
                        newObject.appendTo(theEl);
                    }, 750);
                })();
            }
        }
    };

    videoThumbs.on('click', 'img', function() {
        var self = $(this).parent();

        videoItems.hide();
        stopVideos();
        videos.find('#' + self.data('name')).show();
    });

    appScreenshots.on('click', 'img', function() {
        var self = $(this);

        currentScreenshot.attr('src', self.attr('src'));
    });

    appGeneratorPreviews.on('click', 'a', function(ev) {
        ev.preventDefault();
        var self = $(this);

        appGeneratorItems.removeClass('on');
        appGeneratorDetail.find('#' + self.data('generator')).addClass('on');
    });

    // Navigation toggle for Dev Hub sidebar
    sideNav.on('click', '.nav-title', function() {
        var self = $(this);

        self.parent().toggleClass('active');
    });
})();
