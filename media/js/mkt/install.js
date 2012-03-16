// Hey there! I know how to install apps. Buttons are dumb now.

$('#page').delegate('.button.install', 'click', startInstall);
$('#page').delegate('.button.install', 'mousemove', function() {
    var $button = $(this),
        manifestURL = $button.attr('data-manifest-url');
    (new Image).src = manifestURL;
});

var oldLabel;

function startInstall(e) {
    e.preventDefault();
    e.stopPropagation();
    var $button = $(this),
        manifestURL = $button.attr('data-manifest-url');
    if (manifestURL) {
        oldLabel = $button.html();
        $button.html('Installing&hellip;');
        apps.install(manifestURL, {
            success: installSuccess,
            error: installError
        });
    }
}

function installSuccess() {
    $button.removeClass('install').addClass('installed');
    $button.html('Installed');
}

function installError() {
    $button.html(oldLabel);
}
