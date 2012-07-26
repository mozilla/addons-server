(function() {
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
