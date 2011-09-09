$(document).ready(function() {

    if ($('#packager').length) {
        $('#packager').delegate('.app input:checkbox', 'change', function() {
            var $this = $(this),
                $li = $this.closest('li');
            if ($this.is(':checked')) {
                $li.addClass('selected');
            } else {
                $li.removeClass('selected');
            }
        });
        $('#packager .app input:checkbox').trigger('change');
    }

    if ($('#packager-download').length) {
        $('#packager-download').live('download', function(e) {
            var $this = $(this),
                url = $this.attr('data-downloadurl');
            function fetch_download() {
                $.getJSON(url, function(json) {
                    if (json !== null && 'download_url' in json) {
                        var a = template(
                            '<a href="{url}">{text}<b>{size} {unit}</b></a>'
                        );
                        // L10n: "kB" is for kilobytes, denoting the file size.
                        $this.html(a({
                            url: json['download_url'],
                            text: gettext('Download ZIP'),
                            size: json['size'],
                            unit: gettext('kB')
                        }));
                    } else {
                        // Pause before polling again.
                        setTimeout(fetch_download, 2000);
                    }
                });
            }
            fetch_download();
        });
        $('#packager-download').trigger('download');
    }

});
