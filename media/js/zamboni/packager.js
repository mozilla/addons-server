$(document).ready(function() {

    var $pkgr = $('#packager');
    if ($pkgr.length) {
        // Upon keypress, generates a package name slug from add-on name.
        $pkgr.delegate('#id_name', 'keyup blur', function() {
            var slug = makeslug($('#id_name').val(), '_');
            $('#id_package_name').val(slug);
        }).delegate('#id_package_name', 'blur', function() {
            var $this = $(this);
            $this.val(makeslug($this.val(), '_'));
        });

        // Adds a 'selected' class upon clicking an application checkbox.
        var $supported = $('#supported-apps');
        $supported.delegate('input:checkbox', 'change', function() {
            var $this = $(this),
                $li = $this.closest('li');
            if ($this.is(':checked')) {
                $li.addClass('selected');
            } else {
                $li.removeClass('selected');
            }
        });
        $supported.find('input:checkbox').trigger('change');

        $supported.delegate('select', 'change', function() {
            var $checkbox = $(this).closest('li.row').find('input:checkbox');
            $checkbox.attr('checked', true).trigger('change');
        });
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
