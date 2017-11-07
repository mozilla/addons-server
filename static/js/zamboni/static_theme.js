$(document).ready(function() {
    function BrowserPreview() {
        this.generate = function(id) {
            var svg = SVG(id);
            var $div = $('#' + id);
            var div_height = $div.height();
            // header background
            svg.rect($div.width(), div_height)
               .attr('class', 'accentcolor');
            // main header image
            svg.image('').attr('id', 'svg-header-img')
               .loaded(function(loader) {
                    this.size(loader.width, loader.height);
                });

            // header text
            svg.text('File    Edit   View    History   Bookmarks   Tools   Help')
               .x(5).cy(div_height / 4).font('size', '1.4em')
               .attr('class', 'textcolor');
            svg.text('Inactive Tab')
               .x(160).cy(div_height / 2).font('size', '1.4em')
               .attr('class', 'textcolor');

            // toolbars
            svg.rect($div.width(), div_height / 2)  // toolbar background
               .y(div_height / 2)
               .attr('class', 'toolbar');
            svg.rect(150, div_height / 4)  // active tab background
               .y(div_height / 4)
               .attr('class', 'toolbar');

            // toolbar text
            svg.text('Active Tab')
               .x(10).cy(div_height / 2).font('size', '1.4em')
               .attr('class', 'toolbar_text');
            svg.text('# Most Visited. # Getting Started. # Other Bookmark')
               .x(10).cy(div_height).font('size', '1.4em')
               .attr('class', 'toolbar_text');

            // url field background
            svg.rect(400, (div_height / 4) - 20)
               .x(100).y((div_height / 2) + 10)
               .attr('class', 'toolbar_field');

            // toolbar text
            svg.text('https://addons.mozilla.org/')
               .x(130).y((div_height / 2) + 35).font('size', '1.4em')
               .attr('class', 'toolbar_field_text');

            return svg;
        };

        Object.defineProperty(this, 'accentcolor', {
            set: function(color) {
                if (!color) {
                    color = '#ccc';
                }
                SVG.select('rect.accentcolor').fill(color);
            }
        });

        Object.defineProperty(this, 'textcolor', {
            set: function(color) {
                SVG.select('text.textcolor').fill(color);
            }
        });

        Object.defineProperty(this, 'toolbar', {
            set: function(color) {
                var fill;
                if (!color) {
                    fill = {color: '#fff', opacity: 0.6};
                } else {
                    fill = {color: color, opacity: 1};
                }
                SVG.select('rect.toolbar').fill(fill);
            }
        });

        Object.defineProperty(this, 'toolbar_text', {
            set: function(color) {
                SVG.select('text.toolbar_text').fill(color);
            }
        });

        Object.defineProperty(this, 'toolbar_field', {
            set: function(color) {
                if (!color) {
                    color = '#fff';
                }
                SVG.select('rect.toolbar_field').fill({color: color});
            }
        });

        Object.defineProperty(this, 'toolbar_field_text', {
            set: function(color) {
                SVG.select('text.toolbar_field_text').fill(color);
            }
        });

        this.updateHeaderURL = function(src, width) {
            var header_img = SVG.get('svg-header-img');
            header_img.load(src);
            var div = header_img.parent(SVG.Doc).parent();
            header_img.x(div.clientWidth - width);
        };
    }


    $('#theme-wizard').each(initThemeWizard);


    function initThemeWizard() {
        var $wizard = $(this),
            browserPreview = new BrowserPreview();

        browserPreview.generate('browser-preview');

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
            $wizard.find('a.download').attr('href', '#');
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
            var $this = $(this),
                val = $this.val();
            if (val.indexOf('#') === 0) {
                var rgb = hex2rgb(val);
                $this.attr('data-rgb', format('{0},{1},{2}', rgb.r, rgb.g, rgb.b));
            }
            browserPreview[$this[0].id] = val;
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
                formData.append('upload', blob, 'test.zip');
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

        function hex2rgb(hex) {
            hex = parseInt((hex.indexOf('#') > -1 ? hex.substring(1) : hex), 16);
            return {
                r: hex >> 16,
                g: (hex & 0x00FF00) >> 8,
                b: hex & 0x0000FF
            };
        }
    }

});
