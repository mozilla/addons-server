$(document).ready(function() {

    $('#packager-download').live('download', function(e) {
        var el = $(this),
            url = el.attr('data-downloadurl');

        function fetch_download() {
            $.getJSON(
                url,
                function(json) {
                    if(json !== null && 'download_url' in json) {
                        el.html(format('<a href="{url}">{text}' +
                                       '<small>{size}' + gettext('kb') +
                                       '</small></a>',
                                       {url: json['download_url'],
                                        text: gettext('Download ZIP'),
                                        size: json['size']}));
                    } else {
                        // Pause before polling again.
                        setTimeout(fetch_download, 2000);
                    }
                }
            );
        }

        fetch_download();

    });

    $('#packager-download').trigger('download');

});
