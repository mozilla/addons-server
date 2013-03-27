(function() {
    if (!$('#submit-persona, #addon-edit-license').length) {
        return;
    }

    function checkValid(form) {
        if (form) {
            $(form).find('button[type=submit]').attr('disabled', !form.checkValidity());
        }
    }

    function hex2rgb(hex) {
        var hex = parseInt(((hex.indexOf('#') > -1) ? hex.substring(1) : hex), 16);
        return {
            r: hex >> 16,
            g: (hex & 0x00FF00) >> 8,
            b: (hex & 0x0000FF)
        };
    }

    function loadUnsaved() {
        return JSON.parse($('input[name="unsaved_data"]').val() || '{}');
    }

    function postUnsaved(data) {
        $('input[name="unsaved_data"]').val(JSON.stringify(data));
    }

    var licensesByClass = {
        'copyr': {
            'id': 7,
            'name': gettext('All Rights Reserved')
        },
        'cc-attrib': {
            'id': 9,
            'name': gettext('Creative Commons Attribution 3.0'),
            'url': 'http://creativecommons.org/licenses/by/3.0/'
        },
        'cc-attrib cc-noncom': {
            'id': 10,
            'name': gettext('Creative Commons Attribution-NonCommercial 3.0'),
            'url': 'http://creativecommons.org/licenses/by-nc/3.0/'
        },
        'cc-attrib cc-noncom cc-noderiv': {
            'id': 11,
            'name': gettext('Creative Commons Attribution-NonCommercial-NoDerivs 3.0'),
            'url': 'http://creativecommons.org/licenses/by/3.0/'
        },
        'cc-attrib cc-noncom cc-share': {
            'id': 8,
            'name': gettext('Creative Commons Attribution-NonCommercial-Share Alike 3.0'),
            'url': 'http://creativecommons.org/licenses/by-nc-sa/3.0/'
        },
        'cc-attrib cc-noderiv': {
            'id': 12,
            'name': gettext('Creative Commons Attribution-NoDerivs 3.0'),
            'url': 'http://creativecommons.org/licenses/by-nd/3.0/'
        },
        'cc-attrib cc-share': {
            'id': 13,
            'name': gettext('Creative Commons Attribution-ShareAlike 3.0'),
            'url': 'http://creativecommons.org/licenses/by/3.0/'
        }
    };
    // Build an object for lookups by id: {{7: 'copyr'}, {9: 'cc-attrib'}, ...}.
    var licenseClassesById = _.object(_.map(licensesByClass, function(v, k) {
        return [v.id, k];
    }));

    // Validate the form.
    var $form = $('#submit-persona form');
    $form.delegate('input, select, textarea', 'change keyup paste', function(e) {
        checkValid(e.target.form);
    });
    checkValid($form[0]);

    initLicense();
    initCharCount();
    initPreview();

    function initLicense() {
        var $licenseField = $('#id_license');

        function licenseUpdate(updateList) {
            var licenseClass;
            if ($('input[data-cc="copyr"]:checked').length) {
                licenseClass = 'copyr';
            } else {
                licenseClass = $('input[data-cc]:checked').map(function() {
                    return $(this).data('cc');
                }).toArray().join(' ');
            }
            var license = licensesByClass[licenseClass];
            if (license) {
                var licenseTxt = license['name'];
                if (license['url']) {
                    licenseTxt = format('<a href="{0}" target="_blank">{1}</a>',
                                         license['url'], licenseTxt);
                }
                var $p = $('#persona-license');
                $p.show().find('#cc-license').html(licenseTxt).attr('class', 'license icon ' + licenseClass);
                $licenseField.val(license['id']);
                if (updateList) {
                    updateLicenseList();
                }
            }
        }

        // Hide the other license options when the copyright license is selected.
        $form.delegate('input[name="cc-attrib"]', 'change', function() {
            var $noncc = $('.noncc');
            $noncc.toggleClass('disabled', $(this).data('cc') == 'copyr');
            if ($noncc.find('input[type=radio]:not(:checked)').length == 5) {
                $('input[name="cc-noncom"][value=1], input[name="cc-noderiv"][value=2]').prop('checked', true);
            }
        });
        $('input[data-cc="copyr"]').trigger('change');

        // Whenever a radio field changes, update the license.
        $('input[name^="cc-"]').change(licenseUpdate);
        licenseUpdate();

        if ($licenseField.val()) {
            $('input[type=radio][data-cc="' + licenseClassesById[$licenseField.val()] + '"]').prop('checked', true);
            licenseUpdate();
        }

        $form.delegate('input[type=radio][name=license]', 'change', function() {
            // Upon selecting license from advanced menu, change it in the Q/A format.
            $('.noncc.disabled').removeClass('disabled');
            $('input[name^="cc-"]').prop('checked', false);
            $('input[type=radio][data-cc~="' + licenseClassesById[$(this).val()].split(' ') + '"]').prop('checked', true);
            licenseUpdate(false);
        });

        function updateLicenseList() {
            $('#persona-license-list input[value="' + $licenseField.val() + '"]').prop('checked', true);
        }

        $('#persona-license .select-license').click(_pd(function() {
            $('#persona-license-list').toggle();
            updateLicenseList();
        }));
        updateLicenseList();
    }

    var POST = {};

    function initPreview() {
        var $d = $('#persona-design'),
            upload_finished = function(e) {
                $(this).closest('.row').find('.preview').removeClass('loading');
                $('#submit-persona button').attr('disabled', false);
                updatePersona();
            },
            upload_start = function(e, file) {
                var $p = $(this).closest('.row'),
                    $errors = $p.find('.errorlist');
                if ($errors.length == 2) {
                    $errors.eq(0).remove();
                }
                $p.find('.errorlist').html('');
                $p.find('.preview').addClass('loading').removeClass('error-loading');
                $('#submit-persona button').attr('disabled', true);
            },
            upload_success = function(e, file, upload_hash) {
                var $p = $(this).closest('.row');
                $p.find('input[type="hidden"]').val(upload_hash);
                $p.find('input[type=file], .note').hide();
                $p.find('.preview').attr('src', file.dataURL).addClass('loaded');
                POST[upload_hash] = file.dataURL;  // Remember this as "posted" data.
                updatePersona();
                $p.find('.preview, .reset').show();
            },
            upload_errors = function(e, file, errors) {
                var $p = $(this).closest('.row'),
                    $errors = $p.find('.errorlist');
                $p.find('.preview').addClass('error-loading');
                $.each(errors, function(i, v) {
                    $errors.append('<li>' + v + '</li>');
                });
            };

        $d.delegate('.reset', 'click', _pd(function() {
            var $this = $(this),
                $p = $this.closest('.row');
            $p.find('input[type="hidden"]').val('');
            $p.find('input[type=file], .note').show();
            $p.find('.preview').removeAttr('src').removeClass('loaded');
            updatePersona();
            $this.hide();
        }));

        $d.delegate('input[type="file"]', 'upload_finished', upload_finished)
          .delegate('input[type="file"]', 'upload_start', upload_start)
          .delegate('input[type="file"]', 'upload_success', upload_success)
          .delegate('input[type="file"]', 'upload_errors', upload_errors)
          .delegate('input[type="file"]', 'change', function(e) {
            $(this).imageUploader();
        });

        function updatePersona() {
            var previewSrc = $('#persona-header .preview').attr('src'),
                $preview = $('#persona-preview .persona-viewer');
            if (previewSrc) {
                $preview.css('background-image', 'url(' + previewSrc + ')');
            } else {
                $preview.removeAttr('style');
            }
            var data = {'id': '0'};
            $.each(['name', 'accentcolor', 'textcolor'], function(i, v) {
                data[v] = $d.find('#id_' + v).val();
            });
            // TODO(cvan): We need to link to the CDN-served Persona images since
            //             Personas cannot reference moz-filedata URIs.
            data['header'] = data['headerURL'] = $d.find('#persona-header .preview').attr('src');
            data['footer'] = data['footerURL'] = $d.find('#persona-footer .preview').attr('src');
            $preview.attr('data-browsertheme', JSON.stringify(data));
            var accentcolor = $d.find('#id_accentcolor').attr('data-rgb'),
                textcolor = $d.find('#id_textcolor').val();
            $preview.find('.title, .author').css({
                'background-color': format('rgba({0}, .7)', accentcolor),
                'color': textcolor
            });
        }

        var $color = $('#submit-persona input[type=color]');
        $color.change(function() {
            var $this = $(this),
                val = $this.val();
            if (val.indexOf('#') === 0) {
                var rgb = hex2rgb(val);
                $this.attr('data-rgb', format('{0},{1},{2}', rgb.r, rgb.g, rgb.b));
            }
            updatePersona();
        }).trigger('change');

        // Check for native `input[type=color]` support (i.e., WebKit).
        if ($color[0].type === 'color') {
            $('.miniColors-trigger').hide();
        } else {
            $color.miniColors({
                change: function() {
                    $color.trigger('change');
                    updatePersona();
                }
            });
        }

        $('#id_name').bind('change keyup paste blur', _.throttle(function() {
            $('#persona-preview-name').text($(this).val() || gettext("Your Theme's Name"));
            slugify();
        }, 250)).trigger('change');
        $('#submit-persona').submit(function() {
            postUnsaved(POST);
        });

        POST = loadUnsaved();
        _.each(POST, function(v, k) {
            $('input[value="' + k + '"]').siblings('input[type=file]').trigger('upload_success', [{dataURL: v}, k]);
        });
    }

})();
