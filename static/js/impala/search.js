(function () {
    var appver_input = $('#id_appver');
    var platform_input = $('#id_platform');

    function autofillPlatform(context) {
        var $context = $(context || document.body);

        $('#search', $context).on('autofill', function(e) {
            var $this = $(this);

            // Bail if search is present but not the appver input somehow.
            if (!appver_input.length) {
                return;
            }

            // Populate search form with browser version and OS.
            var gv = z.getVars();

            // Facets are either the ones defined in the URL, or the detected
            // browser version and platform.
            if (!!(gv.appver)) { // Defined in URL parameter
                appver_input.val(gv.appver);
            } else if (z.appMatchesUserAgent) { // Fallback to detected
                // Only do this if firefox 57 or higher. Lower versions default
                // to searching for all add-ons even if they might be
                // incompatible. https://github.com/mozilla/addons-server/issues/5482
                if (VersionCompare.compareVersions(z.browserVersion, '57.0') >= 0) {
                    appver_input.val(z.browserVersion);
                }
            }

            if (!!(gv.platform)) { // Defined in URL parameter
                platform_input.val(gv.platform);
            } else if (z.appMatchesUserAgent) { // Fallback to detected
                platform_input.val(z.platform);
            }
        }).trigger('autofill');
    }


    autofillPlatform();


    $(function() {
        $('#search-facets').on('click', 'li.facet', function(e) {
            var $this = $(this);
            if ($this.hasClass('active')) {
                if ($(e.target).is('a')) {
                    return;
                }
                $this.removeClass('active');
            } else {
                $this.closest('ul').find('.active').removeClass('active');
                $this.addClass('active');
            }
        }).on('highlight', 'a', function(e) {
            // Highlight selection on sidebar.
            var $this = $(this);
            $this.closest('.facet-group').find('.selected').removeClass('selected');
            $this.closest('li').addClass('selected');
        }).on('recount', '.cnt', function(e, newCount) {
            // Update # of results on sidebar.
            var $this = $(this);
            if (newCount.length && $this.html() != newCount.html()) {
                $this.replaceWith(newCount);
            }
        }).on('rebuild', 'a[data-params]', function(e) {
            var $this = $(this),
                url = rebuildLink($this.attr('href'), $this.attr('data-params'));
            $this.attr('href', url);
        });
        if ($('body').hasClass('pjax') && $.support.pjax && z.capabilities.JSON) {
            $('#pjax-results').initSearchPjax($('#search-facets'), '#pjax-results');
        }
    });


    function rebuildLink(url, urlparams, qs) {
        var params = JSON.parseNonNull(urlparams),
            newVars = $.extend(z.getVars(qs, true), params);
        return url.split('?')[0] + '?' + $.param(newVars);
    }


    $.fn.initSearchPjax = function($filters, containerSelector) {
        var $container = $(this),
            container = containerSelector,
            $triggered;

        function pjaxOpen(url) {
            var urlBase = location.pathname + location.search;
            if (!!url && url != '#' && url != urlBase) {
                $.pjax({
                    url: url,
                    container: container,
                    timeout: 5000
                });
            }
        }

        function hijackLink() {
            $triggered = $(this);
            pjaxOpen($triggered.attr('href'));
        }

        function loading() {
            var $wrapper = $container.closest('.results'),
                msg = gettext('Updating results&hellip;'),
                cls = 'updating';
            $wrapper.addClass('loading');

            // The loading throbber is absolutely positioned atop the
            // search results, so we do this to ensure a max-margin of sorts.
            if ($container.outerHeight() > 300) {
                cls += ' tall';
            }

            // Insert the loading throbber.
            $('<div>', {'class': cls, 'html': msg}).insertBefore($container);

            $container.trigger('search.loading');
        }

        function finished() {
            var $wrapper = $container.closest('.results');

            // Initialize install buttons and compatibility checking.
            $.when($container.find('.install:not(.triggered)')
                             .installButton()).done(function() {
                $container.find('.install').addClass('triggered');
                initListingCompat();
            });

            // Remove the loading throbber.
            $wrapper.removeClass('loading').find('.updating').remove();

            // Update the # of matching results on sidebar.
            $filters.find('.cnt').trigger('recount', [$wrapper.find('.cnt')]);

            // Update GET parameters of sidebar anchors.
            $filters.find('a[data-params]').trigger('rebuild');

            // Highlight selection on sidebar.
            if ($triggered) {
                $triggered.trigger('highlight');
            }

            // Update auto-filled appver/platform if there's a user override.
            $('#search').trigger('autofill');

            // Scroll up to top of page.
            $('html, body').animate({scrollTop: 0}, 200);

            $container.trigger('search.finished');
        }

        function turnPages(e) {
            if (fieldFocused(e)) {
                return;
            }
            if (e.which == $.ui.keyCode.LEFT || e.which == $.ui.keyCode.RIGHT) {
                e.preventDefault();
                var sel;
                if (e.which == $.ui.keyCode.LEFT) {
                    sel = '.paginator .prev:not(.disabled)';
                } else {
                    sel = '.paginator .next:not(.disabled)';
                }
                pjaxOpen($container.find(sel).attr('href'));
            }
        }

        $(document).on('click', '.pjax-trigger a', _pd(hijackLink));
        $container.on('pjax:start', loading).on('pjax:end', finished);
        $(document).keyup(_.throttle(turnPages, 300));
    };

})();
