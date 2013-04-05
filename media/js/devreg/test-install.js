define('test-install', ['capabilities'], function(capabilities) {
    z.page.on('submit', '#test-install form', _pd(submitHandler));

    function installSuccess(installer, product) {
        $('#test-install form ul').remove();
    }

    function installError(installer, product, msg) {
        var $errs = $('<ul class="errorlist"></ul>');
        $errs.append(format('<li>{0}</li>', apps.lookupError(msg)));
        $('#test-install form ul').remove();
        $('#test-install form').prepend($errs);
    }

    function submitHandler(e) {
        // product is a bunch of JSON.
        var manifest_url = $('#manifest-url').val(),
            post = {
                src: '',
                device_type: capabilities.getDeviceType(),
                receipt_type: $('#id_receipt_type').val(),
                manifest_url: $('#manifest-url').val()
            },
            data = {},
            product = {
                'is_packaged': false,
                'manifest_url': manifest_url, // the url
                'categories': []
            };

        $.post($(this).data('recordurl'), post).done(function(response) {
            if (response.error) {
                installError(null, product, response.error);
                return;
            }
            if (response.receipt) {
                data.data = {'receipts': [response.receipt]};
            }
            $.when(apps.install(product, data))
             .done(installSuccess)
             .fail(installError);
        }).fail(function(response) {
            installError(null, product, null);
        });
    }
});
