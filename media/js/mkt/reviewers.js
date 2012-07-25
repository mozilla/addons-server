(function() {
    if (z.capabilities.webApps) {
        // Get list of installed apps and mark as such.
        var r = window.navigator.mozApps.getInstalled();
        r.onerror = function(e) {
            throw 'Error calling getInstalled: ' + r.error.name;
        };
        r.onsuccess = function() {
            z.apps = r.result;
            _.each(r.result, function(val) {
                $(window).trigger('app_install_success',
                                  [{'manifestUrl': val.manifestURL}, false])
                         .trigger('app_install_mark',
                                  {'manifestUrl': val.manifestURL});
            });
        };
    } else {
        z.apps = {};
    }

    if (!z.canInstallApps) {
        $(window).trigger('app_install_disabled');
    }

    var $viewManifest = $('#view-manifest'),
        $manifest = $('#manifest-contents');
    if (!$viewManifest.length) {
        return;
    }

    // Prefetch manifest.
    var manifestContents;
    setTimeout(function() {
        $.getJSON($viewManifest.data('url'), function(data) {
            manifestContents = data;

            // Show manifest.
            $viewManifest.click(_pd(function() {
                var $this = $(this),
                    $manifest = $('#manifest-headers, #manifest-contents');
                if ($manifest.length) {
                    $manifest.toggle();
                } else {
                    var contents = '',
                        headers = '';

                    _.each(manifestContents.content.split('\n'), function(v, k) {
                        contents += format('<li>{0}</li>', v);
                    });
                    $('<ol></ol>', {'id': 'manifest-contents', 'html': contents}).insertAfter($this);

                    _.each(manifestContents.headers, function(v, k) {
                        headers += format('<li><b>{0}:</b> {1}</li>', k, v);
                    });
                    $('<ol></ol>', {'id': 'manifest-headers', 'html': headers}).insertAfter($this);
                }
            }));
        });
    }, 200);
})();
