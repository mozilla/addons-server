$(document).ready(function() {

    $('#theme-wizard').each(initThemeWizard);


    function initThemeWizard() {
        var $wizard = $(this);

        $wizard.on('click', '.reset', _pd(function() {
            var $this = $(this),
            $row = $this.closest('.row');
            $row.find('input[type="file"]').click();
        }));

        $wizard.on('change', 'input[type="file"]', function() {
            var $row = $(this).closest('.row');
            var reader = new FileReader(),
                file = getFile($row.find('input[type=file]'));
            if (!file) return;  // don't do anything if no file selected.
            $row.find('input[type=file], .note').hide();

            var $preview_img = $row.find('.preview');
            reader.onload = function(e) {
                $preview_img.attr('src', e.target.result);
                $preview_img.show().addClass('loaded');
                $row.find('.reset').show().css('display', 'block');
                updateManifest();
            };
            reader.readAsDataURL(file);

            var filename = file.name.replace(/\.[^/.]+$/, "");
            $wizard.find('a.download').attr('download', filename + ".zip");
            var name_input = $wizard.find('#theme-name');
            if (!name_input.val()) {
                name_input.val(filename);
            }
        });
        $wizard.find('input[type="file"]').trigger('change');

        $wizard.find('img.preview').on('load', function(e) {
            var $svg_img = $('#svg-header-img'),
                $svg = $('#preview-svg-root');
            $svg_img.attr('href', ($svg_img.src = e.target.src));
            $svg_img.attr('height', e.target.naturalHeight);
            var meetOrSlice = (e.target.naturalWidth < $svg.width())? 'meet' : 'slice';
            $svg_img.attr('preserveAspectRatio', 'xMaxYMin '+ meetOrSlice);
        });

        function updateManifest() {
            textarea = $wizard.find('#manifest').val(generateManifest());
            $wizard.find('button.upload').attr('disabled', ! required_fields_present());
        }

        function getFile($input) {
            file_selector = $input[0];
            return file_selector.files[0];
        }

        function generateManifest() {
            var headerFile = getFile($wizard.find('#header-img')),
                headerURL = headerFile ? headerFile.name : "";

            function colVal(id) {
                return $wizard.find('#' + id).val();
            }

            var colors = {
                "accentcolor": colVal('accentcolor'),
                "textcolor": colVal('textcolor'),
                "toolbar": colVal('toolbar'),
                "toolbar_text": colVal('toolbar_text'),
                "toolbar_field": colVal('toolbar_field'),
                "toolbar_field_text": colVal('toolbar_field_text')
            };
            colors = _.omit(colors, function(value) {return value === "";});

            manifest = {
                name: $wizard.find('#theme-name').val(),
                manifest_version: 2,
                version: $wizard.data('version'),
                theme: {
                    images: {
                        headerURL: headerURL
                    },
                    colors: colors
                }
            };
            return JSON.stringify(manifest, null, 4);
        }

        function buildZip() {
            var zip = new JSZip();
            zip.file('manifest.json', generateManifest());
            var header_img = getFile($wizard.find('#header-img'));
            if (header_img) {
                zip.file(header_img.name, header_img);
            }
            return zip;
        }

        var $color = $wizard.find('input.color-picker');
        $color.change(function() {
            var $this = $(this),
                $svg_element = $('.' + $this[0].id);
            if (!$this.val()) {
                $svg_element.attr('fill', $svg_element.data('fill'));
            } else {
                $svg_element.attr('fill', $this.val());
            }

            updateManifest();
        }).trigger('change');

        $color.minicolors({
            dataUris: true,
            opacity: true,
            format: 'rgb',
            change: function() {
                $color.trigger('change');
                updateManifest();
            }
        });
        /* force the pop-up panel ltr or the images end up in the wrong position. */
        $wizard.find('div.minicolors-panel').attr('dir', 'ltr');

        $wizard.on('change', '#theme-name', updateManifest);

        $wizard.on('click', 'button.upload', _pd(function(event) {
            var $button =  $(event.target);
            var zip = buildZip();
            $button.addClass('uploading').addClass('disabled')
                   .data('upload-text', $button.text())
                   .text($button.data('uploading-text'));

            zip.generateAsync({type: 'blob'}).then(function (blob) {
                var formData = new FormData();
                formData.append('upload', blob, 'upload.zip');
                $.ajax({
                    type: 'POST',
                    url: $button.attr('formaction'),
                    data: formData,
                    processData: false,
                    contentType: false
                }).done(function (data){
                    $('#id_upload').val(data.upload);
                    uploadDone(data);
                });
            }, function (err) {
                console.error(err);
            });
        }));

        function uploadDone(data) {
            if (!data.validation) {
                setTimeout(function() {
                    $.ajax({
                        url: data.url,
                        dataType: 'json',
                        success: uploadDone,
                        error: function (xhr, text, error) {
                            // Fake the validation so we can display as an error.
                            uploadDone({validation:{
                                errors:1,
                                messages:[{message:error}]
                            }});
                        }
                    });
                }, 1000);
            } else {
                if (data.validation.errors === 0 ) {
                    $wizard.find('#submit-describe').submit();
                } else {
                    data.validation.messages.forEach(function(message) {
                       $('.errorlist.validator').append($('<li>', {'html': message.message}));
                       console.error(message);
                    });
                    $('button.upload').removeClass('uploading').removeClass('disabled')
                                      .text($('button.upload').data('upload-text'));
                }
            }
        }

        function required_fields_present() {
            return $wizard.find('#theme-name').val() !== "" &&
                   $wizard.find('#header-img')[0].files.length > 0 &&
                   $wizard.find('#accentcolor').val() !== "" &&
                   $wizard.find('#textcolor').val() !== "";
        }
    }

});
