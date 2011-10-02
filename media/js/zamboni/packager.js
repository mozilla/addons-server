$(document).ready(function() {

    var $pkgr = $('#packager');
    if ($pkgr.length) {
        // Adds a 'selected' class upon clicking an application checkbox.
        $pkgr.delegate('.app input:checkbox', 'change', function() {
            var $this = $(this),
                $li = $this.closest('li');
            if ($this.is(':checked')) {
                $li.addClass('selected');
            } else {
                $li.removeClass('selected');
            }
        });
        $pkgr.find('.app input:checkbox').trigger('change');

        // Upon keypress, generates a package name slug from add-on name.
        function pkg_slugify() {
            var slug = makeslug($('#id_name').val(), '_');
            $('#id_package_name').val(slug);
        }
        $pkgr.delegate('#id_name', 'keyup blur', pkg_slugify);
    }

    if ($('#packager-download').length) {
        $('#packager-download').live('download', function(e) {
            var $this = $(this),
                url = $this.attr('data-downloadurl');
            function fetch_download() {
                $.getJSON(url, function(json) {
                    if (json !== null && 'download_url' in json) {
                        var a = template(
                            '<a href="{url}">{text}<b>{size} kB</b></a>'
                        );
                        $this.html(a({
                            // L10n: {0} is a filename, such as `addon.zip`.
                            text: format(gettext('Download {0}'), json['filename']),
                            size: json['size'],
                            url: json['download_url']
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
