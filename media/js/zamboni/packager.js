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
            var slug = makeslug($('#id_name').val());
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
