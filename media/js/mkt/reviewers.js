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

    // Touch-friendly drop-downs for auxillary nav.
    $('.menu-nav > ul > li > a').click(function(e) {
        var $this = $(this);
        if ($this.siblings('ul').length) {
            e.preventDefault();
            $this.closest('li').toggleClass('open');
        }
    });

    var $viewManifest = $('#view-manifest'),
        $manifest = $('#manifest-contents');
    if (!$viewManifest.length) {
        return;
    }

    // Prefetch manifest.
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
})();
