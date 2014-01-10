/*
 * App submission Tracking Initialization
 * Requirements by Gareth Cull
 * https://bugzilla.mozilla.org/show_bug.cgi?id=957347
 *
 */

define('tracking_app_submit', [], function() {
    if (!_gaq) {
        return;
    }

    var logTracking = false;

    // Step 1: Submit an app button is clicked.
    $('#partnership').on('click', '.submit-app .button', function() {
        _gaq.push([
            '_trackEvent',
            'Sumbit an App CTA',
            'click',
            $(this).text()
        ]);

        if (logTracking) {
            console.log('Submit an app button click tracked...');
        }
    });

    // Step 2: Validate button triggered failed validation.
    $('#upload-webapp-url').on('upload_errors', function(e, r) {
        var numErrors = r.validation.errors;

        _gaq.push([
            '_trackEvent',
            'Hosted App Validation',
            'unsuccessful',
            numErrors + ' validation errors occurred'
        ]);

        if (logTracking) {
            console.log('Failed verify tracked...');
        }
    }).on('upload_success', function(e, r) { // Successful validation.
        var nonErrors = r.validation.warnings + r.validation.notices;

        _gaq.push([
            '_trackEvent',
            'Hosted App Validation',
            'successful',
            nonErrors + ' validation warnings/notices occurred'
        ]);

        if (logTracking) {
            console.log('Successful verify tracked...');
        }
    });

    // Step 2: App form submitted. Track which app types were selected.
    $('#upload-webapp').on('submit', function() {
        _gaq.push([
            '_setCustomVar',
            14,
            'Selected App Types',
            $('#id_free_platforms').val().join(', '),
            1
        ]);

        if (logTracking) {
            console.log('App types selection tracked...');
        }
    });

    // MDN link was clicked. Opens in a new tab so flow is uninterrupted.
    $('.learn-mdn').on('click', 'a', function() {
        _gaq.push([
            '_trackEvent',
            'MDN Exits',
            'click',
            'MDN App Manifests'
        ]);

        if (logTracking) {
            console.log('MDN link tracked...');
        }
    });

    // Step 3: Form submitted. Track which categories were selected.
    $('#submit-media').on('submit', function() {
        var cats = [];
        $('.addon-categories input:checked').each(function() {
            cats.push($(this).closest('label').text());
        });

        _gaq.push([
            '_setCustomVar',
            15,
            'Dev: App Category Submitted',
            cats.join(', '),
            1
        ]);

        if (logTracking) {
            console.log('Category choices tracked...');
        }
    });

    // Step 4: Click the 'setup content ratings' button.
    if ($('#submit-next-steps').length) {
        _gaq.push([
            '_trackEvent',
            'App Successfully Submitted',
            'onload',
            location.href
        ]);

        if (logTracking) {
            console.log('Step 4 page load tracked...');
        }
    }
});
