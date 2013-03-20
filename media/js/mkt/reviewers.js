(function() {

    if (z.capabilities.mobile) {
        z.body.addClass('mobile');
    }
    if (z.capabilities.tablet) {
        z.body.addClass('tablet');
    }
    if (z.capabilities.desktop) {
        z.body.addClass('desktop');
    }

    var $viewManifest = $('#view-manifest'),
        $manifest = $('#manifest-contents'),
        $search = $('#queue-search');

    // Prefetch manifest.
    if ($viewManifest.length) {
        $.getJSON($viewManifest.data('url'), function(data) {
            var manifestContents = data;

            // Show manifest.
            $viewManifest.click(_pd(function() {
                var $this = $viewManifest,
                    $manifest = $('#manifest-headers, #manifest-contents');
                if ($manifest.length) {
                    $manifest.toggle();
                } else {
                    if (!manifestContents.success) {
                        // If requests couldn't fetch the manifest, let Firefox render it.
                        $('<iframe>', {'id': 'manifest-contents',
                                       'src': 'view-source:' + $this.data('manifest')}).insertAfter($this);
                    } else {
                        var contents = '',
                            headers = '';

                        _.each(manifestContents.content.split('\n'), function(v, k) {
                            if (v) {
                                contents += format('<li>{0}</li>', v);
                            }
                        });
                        $('<ol>', {'id': 'manifest-contents', 'html': contents}).insertAfter($this);

                        if (manifestContents.headers) {
                            _.each(manifestContents.headers, function(v, k) {
                                headers += format('<li><b>{0}:</b> {1}</li>', k, v);
                            });
                            $('<ol>', {'id': 'manifest-headers', 'html': headers}).insertAfter($this);
                        }

                        if (manifestContents.permissions) {
                            var permissions = format('<h4>{0}</h4><dl>', gettext('Requested Permissions:'));
                            permissions += _.map(
                                manifestContents.permissions,
                                function(details, permission) {
                                    var type;
                                    if (details.type) {
                                        switch (details.type) {
                                            case 'cert':
                                                type = gettext('Certified');
                                                break;
                                            case 'priv':
                                                type = gettext('Privileged');
                                                break;
                                            case 'web':
                                                type = gettext('Unprivileged');
                                        }
                                    }
                                    return format('<dt>{0}</dt><dd>{1}, {2}</dd>',
                                                  permission, type, details.description || gettext('No reason given'));
                                }
                            ).join('');
                            $('<div>', {'id': 'manifest-permissions', 'html': permissions}).insertAfter($this);
                        }
                    }
                }
            }));
        });
    }

    // Reviewer tool search.
    var search_results = getTemplate($('#queue-search-template'));
    var search_result_row = getTemplate($('#queue-search-row-template'));
    var no_results = getTemplate($('#queue-search-empty-template'));
    var $clear = $('#clear-queue-search'),
        $appQueue = $('.search-toggle'),
        $searchIsland = $('#search-island');

    $clear.click(_pd(function() {
        $appQueue.show();
        $('#id_q').val('');
        $clear.hide();
        $searchIsland.hide();
    }));

    if ($search.length) {
        var api_url = $search.data('api-url');
        $search.on('submit', 'form', _pd(function() {
            var $form = $(this);
            $.get(api_url, $form.serialize()).done(function(data) {
                // Hide app queue.
                $appQueue.hide();
                $clear.show();
                // Show results.
                if (data.meta.total_count === 0) {
                    $searchIsland.html(no_results({})).show();
                } else {
                    var results = [];
                    $.each(data.objects, function(i, item) {
                        results.push(search_result_row(item));
                    });
                    $searchIsland.html(
                        search_results({rows: results.join('')})).show();
                }
            });
        }));
    }

})();
