$(document).ready(function() {
    function StaticThemeBrowserPreview() {
        this.generate = function($div) {
            $div.append($(
                '<svg id="SvgjsSvg1006" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg" version="1.1" xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:svgjs="http://svgjs.com/svgjs">' +
                '<defs id="SvgjsDefs1007"></defs>' +
                '<rect id="SvgjsRect1008" width="900" height="200" class="accentcolor"></rect>' +
                '<image id="svg-header-img" width="0" height="0"></image>' +
                '<text id="SvgjsText1010" font-family="Helvetica, Arial, sans-serif" x="5" y="34.20000076293945" font-size="1.4em" class="textcolor" fill=""><tspan id="SvgjsTspan1011" dy="1.8199999999999998" x="5">File    Edit   View    History   Bookmarks   Tools   Help</tspan></text>' +
                '<text id="SvgjsText1012" font-family="Helvetica, Arial, sans-serif" x="160" y="84.20000076293945" font-size="1.4em" class="textcolor" fill=""><tspan id="SvgjsTspan1013" dy="1.8199999999999998" x="160">Inactive Tab</tspan></text>' +
                '<rect id="SvgjsRect1014" width="900" height="100" y="100" class="toolbar" fill="#fff" fill-opacity="0.6"></rect>' +
                '<rect id="SvgjsRect1015" width="150" height="50" y="50" class="toolbar" fill="#fff" fill-opacity="0.6"></rect>' +
                '<text id="SvgjsText1016" font-family="Helvetica, Arial, sans-serif" x="10" y="84.20000076293945" font-size="1.4em" class="toolbar_text" fill=""><tspan id="SvgjsTspan1017" dy="1.8199999999999998" x="10">Active Tab</tspan></text>' +
                '<text id="SvgjsText1018" font-family="Helvetica, Arial, sans-serif" x="10" y="184.20000076293945" font-size="1.4em" class="toolbar_text" fill=""><tspan id="SvgjsTspan1019" dy="1.8199999999999998" x="10"># Most Visited. # Getting Started. # Other Bookmark</tspan></text>' +
                '<rect id="SvgjsRect1020" width="400" height="30" x="100" y="110" class="toolbar_field" fill="#fff"></rect>' +
                '<text id="SvgjsText1021" font-family="Helvetica, Arial, sans-serif" x="130" y="128.20000076293945" font-size="1.4em" class="toolbar_field_text" fill=""><tspan id="SvgjsTspan1022" dy="1.8199999999999998" x="130">https://addons.mozilla.org/</tspan></text>' +
                '</svg>'));
        };

        Object.defineProperty(this, 'accentcolor', {
            set: function(color) {
                if (!color) {
                    color = '#ccc';
                }
                $('rect.accentcolor').attr('fill', color);
            }
        });

        Object.defineProperty(this, 'textcolor', {
            set: function(color) {
                $('text.textcolor').attr('fill', color);
            }
        });

        Object.defineProperty(this, 'toolbar', {
            set: function(color) {
                var attrs;
                if (!color) {
                    attrs = {'fill': '#fff', 'fill-opacity': "0.6"};
                } else {
                    attrs = {'fill': color, 'fill-opacity': "1"};
                }
                $('rect.toolbar').attr(attrs);
            }
        });

        Object.defineProperty(this, 'toolbar_text', {
            set: function(color) {
                $('text.toolbar_text').attr('fill', color);
            }
        });

        Object.defineProperty(this, 'toolbar_field', {
            set: function(color) {
                if (!color) {
                    color = '#fff';
                }
                $('rect.toolbar_field').attr('fill', color);
            }
        });

        Object.defineProperty(this, 'toolbar_field_text', {
            set: function(color) {
                $('text.toolbar_field_text').attr('fill', color);
            }
        });

        this.updateHeaderURL = function(src, width) {
            var header_img = $('#svg-header-img');

            var img  = new window.Image();
            $(img).on('load', function() {
                header_img.attr({width: img.width, height: img.height});
            });
            header_img.attr('href', (img.src = header_img.src = src));

            var div = header_img.parents('div')[0];
            header_img.attr('x', div.clientWidth - width);
        };
    }


    $('#theme-wizard').each(initThemeWizard);


    function initThemeWizard() {
        var $wizard = $(this),
            browserPreview = new StaticThemeBrowserPreview();

        browserPreview.generate($('#browser-preview'));

        $wizard.on('click', '.reset', _pd(function() {
            var $this = $(this),
            $row = $this.closest('.row');
            $row.find('input[type="hidden"]').val('');
            $row.find('input[type=file], .note').show();
            var preview = $row.find('.preview');
            preview.removeAttr('src').removeClass('loaded');
            $this.hide();
        }));

        $wizard.on('change', 'input[type="file"]', function() {
            var $row = $(this).closest('.row');
            var reader = new FileReader(),
                file = getFile($row.find('input[type=file]'));
            if (!file) return;  // don't do anything if no file selected.
            $row.find('input[type=file], .note').hide();

            reader.onload = (function(aImg) { return function(e) {
                aImg.attr('src', e.target.result);
                aImg.show().addClass('loaded');
                $row.find('.reset').show();
                updateManifest();
            };})($row.find('.preview'));
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
            img = e.target;
            browserPreview.updateHeaderURL(img.src, img.naturalWidth);
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
                version: '1.0',
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
            var $this = $(this);
            browserPreview[$this[0].id] = $this.val();
            updateManifest();
        }).trigger('change');

        $color.minicolors({
            dataUris: true,
            change: function() {
                $color.trigger('change');
                updateManifest();
            }
        });

        $wizard.on('click', 'button.upload', _pd(function(event) {
            var $button =  $(event.target);
            var zip = buildZip();
            $button.addClass('uploading').addClass('disabled')
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
            //console.log(data);
            if (!data.validation) {
                setTimeout(function() {
                    $.ajax({
                        url: data.url,
                        dataType: 'json',
                        success: uploadDone
                    });
                }, 1000);
            } else {
                $wizard.find('#submit-describe').submit();
            }
        }

        function required_fields_present() {
            return $wizard.find('#header-img')[0].files.length > 0 &&
                   $wizard.find('#accentcolor').val() !== "" &&
                   $wizard.find('#textcolor').val() !== "";
        }
    }

});
