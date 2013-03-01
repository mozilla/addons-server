$(document).ready(function() {
    // Edit Add-on
    if (document.getElementById('edit-addon')) {
        initEditAddon();
    }

    // Save manifest if passed in
    var params = z.getVars();
    if('manifest' in params && z.capabilities.sessionStorage) {
        window.sessionStorage['manifest_url'] = params['manifest'];
    }

    //Ownership
    if (document.getElementById('author_list')) {
        initAuthorFields();
        initLicenseFields();
    }

    //Payments
    if ($('.payments').length) {
        initPayments();
    }

    // Submission process
    if ($('.addon-submission-process').length) {
        initLicenseFields();
        initCharCount();
        initSubmit();
    }

    // Validate addon (standalone)
    if ($('.validate-addon').length) {
        initSubmit();
    }

    // Submission > Describe
    if (document.getElementById('submit-describe')) {
        initCatFields();
    }

    // Submission > Descript > Summary
    if ($('.addon-submission-process #submit-describe').length) {
        initTruncateSummary();
    }

    // Submission > Media
    if (document.getElementById('submit-media')) {
        initUploadIcon();
        initUploadImages();
        initUploadPreview();
    }

    // Add-on uploader
    if(document.getElementById('upload-app')) {
        var opt = {'cancel': $('.upload-file-cancel') };
        $('#upload-app').packagedAppUploader(opt);
    }

    var $webapp_url = $('#upload-webapp-url'),
        $validate_form = $('#validate-field'),
        $validate_button = $('#validate_app'),
        $submit_footer = $('#upload-webapp').find('footer');

    if ($webapp_url.length) {
        if (!$webapp_url.val()) {
            if (z.capabilities.sessionStorage) {
                $webapp_url.val(window.sessionStorage['manifest_url']);
            }
        }
        var attempts = $webapp_url.val().length;
        $webapp_url.bind('keyup change paste blur', function(e) {
            var $this = $(this),
                // Ensure it's at least "protocol://host/something".
                match = $this.val().match(/^(.+):\/\/(.+)/);
            if ($this.attr('data-input') != $this.val()) {
                // Show warning if 8+ characters have been typed but there's no protocol.
                if ($this.val().length >= 8 && !$this.val().match(/^(.+):\/\//)) {
                    $('#validate-error-protocol').addClass('protocol visible')
                        .parent().addClass('show-tip');
                } else {
                    $('#validate-error-protocol').removeClass('protocol visible')
                        .parent().removeClass('show-tip');
                }

                $submit_footer.filter(':visible').addClass('hidden');
                $('.upload-details .hint:hidden').show();

                // Show the button if valid.
                $validate_button.toggleClass('disabled', !match).removeClass('hovered');

                $this.attr('data-input', $this.val());
                $('#upload-status-results').remove();
                $('#upload-file button.upload-file-submit').attr('disabled', true);

                // Count the keyups to watch for a paste (which we'll assume is attempts=1).
                attempts++;
                if (!$this.val()) {
                    attempts = 0;
                }
                // Was a paste so validate immediately.
                if (e.type == 'paste' || (attempts == 1 && $this.val().length >= 8)) {
                    $validate_button.removeClass('disabled');
                    $validate_form.submit();
                }
            }
        }).trigger('keyup')
        .bind('upload_finished', function(e, success, r, message) {
            $('#upload-status-results').remove();
            $webapp_url.removeClass('loading');

            var $error_box = $('<div>', {'id': 'upload-status-results', 'class':
                                         'status-' + (success ? 'pass' : 'fail')}).show(),
                $eb_messages = $("<ul>", {'id': 'upload_errors'}),
                messages = r.validation.messages || [];

            $error_box.append($("<strong>", {'text': message}));
            $error_box.append($eb_messages);

            $.each(messages, function(i, m) {
                var li = $('<li>', {'html': m.message});
                $eb_messages.append(li);
            });

            if (r && r.full_report_url) {
                // There might not be a link to the full report
                // if we get an early error like unsupported type.
                $error_box.append($("<a>", {'href': r.full_report_url,
                                            'target': '_blank',
                                            'class': 'view-more',
                                            'text': gettext('See full validation report')}));
            }

            $('.upload-status').append($error_box);

            if (z.capabilities.sessionStorage) {
                if (success) {
                    delete window.sessionStorage['manifest_url'];
                } else {
                    window.sessionStorage['manifest_url'] = $webapp_url.val();
                }
            }

            // Show footer to "Continue" only if there was a success.
            $submit_footer.toggleClass('hidden', !success);
            $('.upload-details .hint').hide();
        })
        .bind('upload_errors', function(e, r) {
            var v = r.validation,
                error_message = format(ngettext(
                    "Your app failed validation with {0} error.",
                    "Your app failed validation with {0} errors.",
                    v.errors), [v.errors]);

            $(this).trigger('upload_finished', [false, r, error_message]);
            $validate_button.removeClass('disabled');
        })
        .bind('upload_success', function(e, r) {
            var message = "",
                v = r.validation,
                warnings = v.warnings + v.notices;

            if(warnings > 0) {
                message = format(ngettext(
                            "Your app passed validation with no errors and {0} message.",
                            "Your app passed validation with no errors and {0} messages.",
                            warnings), [warnings]);
            } else {
                message = gettext("Your app passed validation with no errors or messages.");
            }

            $(this).trigger('upload_finished', [true, r, message]);
            $('#upload-file button.upload-file-submit').removeAttr('disabled').focus();
            $validate_button.addClass('hovered disabled');
        });

        // Add protocol if needed
        $('#validate-error-protocol a').click(_pd(function() {
            $webapp_url.val($(this).text() + $webapp_url.val())
                       .focus()
                       .trigger('keyup');
        }));

        $validate_form.submit(function() {
            if ($validate_button.hasClass('disabled')) return false;

            $validate_button.addClass('disabled');
            $.post(
                $webapp_url.attr('data-upload-url'),
                {'manifest': $('#upload-webapp-url').val()},
                check_webapp_validation
            );
            $webapp_url.addClass('loading');
            return false;
        });
        function check_webapp_validation(results) {
            var $upload_field = $('#upload-webapp-url');
            $('#id_upload').val(results.upload);
            $('#id_packaged').val('');
            if(results.error) {
                $upload_field.trigger("upload_finished", [false, results, results.error]);
            } else if(!results.validation) {
                setTimeout(function(){
                    $.ajax({
                        url: results.url,
                        dataType: 'json',
                        success: check_webapp_validation
                    });
                }, 1000);
            } else {
                if(results.validation.errors) {
                    $upload_field.trigger("upload_errors", [results]);
                } else {
                    $upload_field.trigger("upload_success", [results]);
                }
            }
        }
    }

    $('.invisible-upload a').click(_pd);

    // when to start and stop image polling
    var $media = $('.edit-media');
    if ($media.length && $media.attr('data-checkurl') !== undefined) {
        imageStatus.start(true, true);
    }
    $media.bind('click', function() {
        imageStatus.cancel();
    });

    // hook up various links related to current version status
    $('#modal-delete').modal('#delete-addon', {
        width: 400,
        callback: function(obj) {
            return fixPasswordField(this);
        }
    });
    $('#modal-disable').modal('#disable-addon', {
        width: 400,
        callback: function(d) {
            $('.version_id', this).val($(d.click_target).attr('data-version'));
            return true;
        }
    });

    if (document.getElementById('version-list')) {
        var status = $('#version-status').data('status');
        var versions = $('#modal-delete-version').data('versions');
        $('#modal-delete-version').modal('.delete-version', {
            width: 400,
            callback: function(d) {
                var version = versions[$(d.click_target).data('version')],
                    $header = $('h3', this);
                $header.text(format($header.attr('data-tmpl'), version));
                $('.version-id', this).val(version.id);
                if (versions.num == 1) {
                    $('#last-version, #last-version-other').show();
                    if (status == 2) {  // PENDING
                        $('#last-version-pending').show();
                    } else if (status == 4) {  // PUBLIC
                        $('#last-version-public').show();
                    }
                } else {
                    $('#not-last-version').show();
                }
            }
        });
    }

    // In-app payments config.
    if ($('#in-app-config').length) {
        initInAppConfig($('#in-app-config'));
    }
});


$(document).ready(function() {
    $.ajaxSetup({cache: false});

    $('.modal-delete').each(function() {
        var el = $(this);
        el.modal(el.closest('li').find('.delete-addon'), {
            width: 400,
            callback: function(obj) {
                fixPasswordField(this);
                return {pointTo: $(obj.click_target)};
            }
        });
    });

    truncateFields();

    z.page.on('click', '.addon-edit-cancel', _pd(function() {
        var $this = $(this),
            parent_div = $this.closest('.edit-addon-section');
        parent_div.load($this.attr('href'), function() {
            hideSameSizedIcons();
            z.refreshL10n();
        });
        if (parent_div.is('.edit-media')) {
            imageStatus.start(true, true);
        }
    }));
});


(function initFormPerms() {
    z.noEdit = $("body").hasClass("no-edit");
    if (z.noEdit) {
        $primary = $(".primary");
        var $form_els = $primary.find("input, select, textarea, button");
        $form_els.attr("disabled", "disabled");
        var $link_els = $primary.find("a.button");
        $link_els.addClass("disabled");
        $primary.find("span.handle, a.remove").hide();
        $('.primary h2 a.button').remove();
        $(document).ready(function() {
            $form_els.unbind().undelegate();
            $link_els.unbind().undelegate();
        });
    }
})();


function truncateFields() {
    return;
}


function addonFormSubmit() {
    parent_div = $(this);

    (function(parent_div){
        // If the baseurl changes (the slug changed) we need to go to the new url.
        var baseurl = function(){
            return parent_div.find('#addon-edit-basic').attr('data-baseurl');
        };

        // This exists because whoever wrote `imageStatus` didn't think there'd
        // ever be anything besides icons and previews.
        $('.image_preview_box .image img').each(function(index, el) {
            el.src = imageStatus.newurl(el.src);
        });

        $('.edit-media-button button').attr('disabled', false);
        $('form', parent_div).submit(function(e){
            e.preventDefault();
            var old_baseurl = baseurl();
            parent_div.find(".item").removeClass("loaded").addClass("loading");
            var $document = $(document),
                scrollBottom = $document.height() - $document.scrollTop(),
                $form = $(this),
                hasErrors = $form.find('.errorlist').length;

            $.post($form.attr('action'), $form.serialize(), function(d) {
                parent_div.html(d).each(addonFormSubmit);
                if (!hasErrors && old_baseurl && old_baseurl !== baseurl()) {
                    document.location = baseurl();
                }
                $document.scrollTop($document.height() - scrollBottom);
                truncateFields();
                annotateLocalizedErrors(parent_div);
                if (parent_div.is('.edit-media')) {
                    imageStatus.start(true, true);
                    hideSameSizedIcons();
                }
                if ($form.find('#addon-categories-edit').length) {
                    initCatFields();
                }

                if (!hasErrors) {
                    var e = $(format('<b class="save-badge">{0}</b>',
                                     [gettext('Changes Saved')]))
                              .appendTo(parent_div.find('h2').first());
                    setTimeout(function(){
                        e.css('opacity', 0);
                        setTimeout(function(){ e.remove(); }, 200);
                    }, 2000);
                }
            });
        });
        reorderPreviews();
        z.refreshL10n();
    })(parent_div);
}


$("#user-form-template .email-autocomplete")
    .attr("placeholder", gettext("Enter a new team member's email address"));

function addManifestRefresh() {
    z.page.on('click', '#manifest-url a.button', _pd(function(e) {
        $('#manifest-url th.label span.hint').remove();
        $.post(
            $(e.target).data("url")
        ).then(function() {
            var refreshed = gettext('Refreshed');
            $('#manifest-url th.label').append('<span class="hint">' + refreshed + '</span>');
        });
    }));
}

function initEditAddon() {
    if (z.noEdit) return;

    // Load the edit form.
    $('#edit-addon').delegate('h2 a', 'click', function(e){
        e.preventDefault();

        var a = e.target;
        parent_div = $(a).closest('.edit-addon-section');

        (function(parent_div, a){
            parent_div.find(".item").addClass("loading");
            parent_div.load($(a).attr('data-editurl'), function(){
                parent_div.trigger('editLoaded');
                if (parent_div.find('#addon-categories-edit').length) {
                    initCatFields();
                }
                if (parent_div.find('#manifest-url').length) {
                    addManifestRefresh();
                }
                $(this).each(addonFormSubmit);
                initInvisibleUploads();
            });
        })(parent_div, a);

        return false;
    });

    // Init icon javascript.
    hideSameSizedIcons();
    initUploadIcon();
    initUploadImages();
    initUploadPreview();
}


function create_new_preview_field() {
    var forms_count = $('#id_files-TOTAL_FORMS').val(),
        last = $('#file-list .preview').last(),
        last_clone = last.clone();

    $('input, textarea, div', last_clone).each(function(){
        var re = new RegExp(format("-{0}-", [forms_count-1])),
            new_count = "-"+forms_count+"-",
            el = $(this);

        $.each(['id','name','data-name'], function(k,v){
            if(el.attr(v)) {
                el.attr(v, el.attr(v).replace(re, new_count));
            }
        });
    });
    last.after(last_clone);
    $('#id_files-TOTAL_FORMS').val(parseInt(forms_count, 10) + 1);

    return last;
}

function renumberPreviews() {
    var $files = $('#file-list'),
        maxPreviews = $files.attr('data-max'),
        $previews = $files.children('.preview:visible');
    $previews.each(function(i, el) {
        $(this).find('.position input').val(i);
    });
    $previews.find('.handle').toggle($previews.length > 1);
    // Limit to some number of previews.
    if (maxPreviews) {
        $files.siblings('.invisible-upload').toggle(
            $previews.length < parseInt(maxPreviews, 10));
    }
    // If there's an error expose the invisible upload.
    if ($files.find('.error-loading:visible').length) {
        $files.siblings('.invisible-upload').show();
    }
}

function reorderPreviews() {
    var preview_list = $("#file-list");

    if (preview_list.length) {
        preview_list.sortable({
            items: ".preview:visible",
            handle: ".handle",
            containment: preview_list,
            tolerance: "pointer",
            update: renumberPreviews
        });

        renumberPreviews();
    }
}

function initUploadPreview() {
    var forms = {},
        form,
        $f = $('.edit-media, #submit-media');

    function upload_start_all(e) {
        // Remove old errors.
        $('.edit-addon-media-screenshot-error').hide();

        // Don't let users submit a form.
        $('.edit-media-button button, #submit-media button.prominent').attr('disabled', true);
    }

    function upload_finished_all(e) {
        // They can submit again
        $('.edit-media-button button, #submit-media button.prominent').attr('disabled', false);
    }

    function upload_start(e, file) {
        if ($(this).is('.edit-admin-promo')) {
            // No formsets here, so easy peasy!
            form = $('.preview');
            form.find('.delete input').removeAttr('checked');
        } else {
            form = create_new_preview_field();
        }
        forms['form_' + file.instance] = form;

        var $thumb = form.show().find('.preview-thumb');
        $thumb.addClass('loading');
        if (file.type.indexOf('video') > -1) {
            $thumb.replaceWith(format(
                '<video controls class="preview-thumb loading" src="{0}" ' +
                'preload="auto" type="video/webm"></video>', file.dataURL));
        } else {
            $thumb.css('background-image', 'url(' + file.dataURL + ')');
        }
        renumberPreviews();
    }

    function upload_finished(e, file) {
        form = forms['form_' + file.instance];
        form.find('.preview-thumb').removeClass('loading');
        renumberPreviews();
    }

    function upload_success(e, file, upload_hash) {
        form = forms['form_' + file.instance];
        form.find('[name$="upload_hash"]').val(upload_hash);
        form.find('[name$="unsaved_image_type"]').val(file.type);
        form.find('[name$="unsaved_image_data"]').val(file.dataURL);
    }

    function upload_errors(e, file, errors) {
        var form = forms['form_' + file.instance],
            $el = $(form),
            error_msg = gettext("There was an error uploading your file."),
            $error_title = $('<strong>').text(error_msg),
            $error_list = $('<ul>');

        $el.addClass('edit-addon-media-screenshot-error');

        $.each(errors, function(i, v){
            $error_list.append('<li>' + v + '</li>');
        });

        $el.find('.preview-thumb').addClass('error-loading');

        $el.find('.edit-previews-text').addClass('error').html('')
                                       .append($error_title)
                                       .append($error_list);
        $el.find('.delete input').attr('checked', 'checked');
        renumberPreviews();
    }

    if (z.capabilities.fileAPI) {
        $f.delegate('.screenshot_upload', 'upload_finished', upload_finished)
          .delegate('.screenshot_upload', 'upload_success', upload_success)
          .delegate('.screenshot_upload', 'upload_start', upload_start)
          .delegate('.screenshot_upload', 'upload_errors', upload_errors)
          .delegate('.screenshot_upload', 'upload_start_all', upload_start_all)
          .delegate('.screenshot_upload', 'upload_finished_all', upload_finished_all)
          .delegate('.screenshot_upload', 'change', function(e){
                $(this).imageUploader();
          });
    }

    $('.edit-media, .submit-media').delegate('#file-list .remove', 'click', function(e){
        e.preventDefault();
        var $this = $(this),
            row = $this.closest('.preview');
        row.slideUp(300, renumberPreviews);
        if($this.closest('.edit-media').is('#edit-addon-admin')) {
            // If we're updating the promo, we need to delete the existing
            // promo immediately because we recycle the existing .preview
            // element. The delete value will get overwritten and I'll be a
            // sad basta.
            var $form = $this.closest('form');
            $.post($form.attr('action'), $form.serialize() + '&DELETE=on');
        } else {
            row.find('.delete input').attr('checked', 'checked');
        }
    });

    // Display images that were already uploaded but not yet saved
    // because of other non-related form errors.
    $('#file-list .preview_extra [name$="unsaved_image_data"]').each(function(i, elem) {
        var $data = $(elem);
        if ($data.val()) {
            var $thumb = $data.parents('.preview').find('.preview-thumb'),
                file_type = $data.siblings('input[name$="unsaved_image_type"]').val();
            if (file_type.indexOf('video') > -1) {
                $thumb.replaceWith(format(
                    '<video controls class="preview-thumb" src="{0}" ' +
                    'type="video/webm"></video>',
                    $data.val()));
            } else {
                $thumb.css('background-image', 'url(' + $data.val() + ')');
            }
        }
    });
}

function initInvisibleUploads() {
    if (!z.capabilities.fileAPI) {
        $('.invisible-upload').addClass('legacy');
    }
}

function initUploadIcon() {
    initInvisibleUploads();

    $('.edit-media, #submit-media').delegate('#icons_default a', 'click', function(e){
        e.preventDefault();

        var $error_list = $('#icon_preview').parent().find('.errorlist'),
            $parent = $(this).closest('li');

        $('input', $parent).attr('checked', true);
        $('#icons_default a.active').removeClass('active');
        $(this).addClass('active');

        $("#id_icon_upload").val("");
        $('#icon_preview').show();

        $('#icon_preview_32 img').attr('src', $('img', $parent).attr('src'));
        $('#icon_preview_64 img').attr('src', $('img',
                $parent).attr('src').replace(/32/, '64'));
        $('#icon_preview_128 img').attr('src', $('img',
                $parent).attr('src').replace(/32/, '128'));

        $error_list.html("");
    });

    // Upload an image!
    var $f = $('.edit-media, #submit-media'),

        upload_errors = function(e, file, errors){
            var $error_list = $('#icon_preview').parent().find('.errorlist');
            $.each(errors, function(i, v){
                $error_list.append("<li>" + v + "</li>");
            });
        },

        upload_success = function(e, file, upload_hash) {
            $('#id_icon_upload_hash').val(upload_hash);
            $('#icons_default a.active').removeClass('active');

            $('#icon_preview img').attr('src', file.dataURL);
            $('#id_unsaved_icon_data').val(file.dataURL);

            $('#icons_default input:checked').attr('checked', false);
            $('input[name="icon_type"][value="'+file.type+'"]')
                    .attr('checked', true);
        },

        upload_start = function(e, file) {
            var $error_list = $('#icon_preview').parent().find(".errorlist");
            $error_list.html("");

            $('.icon_preview', $f).addClass('loading');

            $('.edit-media-button button').attr('disabled', true);
        },

        upload_finished = function(e) {
            $('.icon_preview', $f).removeClass('loading');
            $('.edit-media-button button').attr('disabled', false);
        };

    $f.delegate('#id_icon_upload', 'upload_success', upload_success)
      .delegate('#id_icon_upload', 'upload_start', upload_start)
      .delegate('#id_icon_upload', 'upload_finished', upload_finished)
      .delegate('#id_icon_upload', 'upload_errors', upload_errors)
      .delegate('#id_icon_upload', 'change', function(e) {
        if (z.capabilities.fileAPI) {
            $(this).imageUploader();
        } else {
            $('#icon_preview').hide();
        }
      });

    // Display icons that were already uploaded but not yet saved because of
    // other non-related form errors.
    $('#submit-media [name$="unsaved_icon_data"]').each(function(i, elem) {
        var $data = $(elem);
        if ($data.val()) {
            $('#submit-media #icon_preview img').attr('src', $data.val());
        }
    });
}

function initUploadImages() {
    var forms = {},
        form;

    function upload_start_all(e) {
        // Remove old errors.
        $(this).closest('.image_preview').find('.errorlist').hide();
        // Don't let users submit a form.
        $('.edit-media-button button, #submit-media button.prominent').attr('disabled', true);
    }

    function upload_finished_all(e) {
        // They can submit again
        $('.edit-media-button button, #submit-media button.prominent').attr('disabled', false);
    }

    function upload_start(e, file) {
        var $input = $(this);
        forms['form_' + file.instance] = form = $input.closest('.image_preview');

        var $thumb = form.show().find('.image');
        $thumb.addClass('loading');
        $thumb.find('img').attr('src', file.dataURL);
    }

    function upload_finished(e, file) {
        form = forms['form_' + file.instance];
        form.find('.image').removeClass('loading');
    }

    function upload_success(e, file, upload_hash) {
        form = forms['form_' + file.instance];
        form.find('[name$="upload_hash"]').val(upload_hash);
        form.find('[name$="unsaved_image_data"]').val(file.dataURL);
    }

    function upload_errors(e, file, errors) {
        var form = forms['form_' + file.instance],
            $error_list = form.find('.errorlist');

        $.each(errors, function(i, v){
            $error_list.append('<li>' + v + '</li>');
        });

        form.find('.image').addClass('error-loading');
    }
    if (z.capabilities.fileAPI) {
        var $f = $('.edit-media, #submit-media');
        $f.delegate('.image_asset_upload', 'upload_finished', upload_finished)
          .delegate('.image_asset_upload', 'upload_success', upload_success)
          .delegate('.image_asset_upload', 'upload_start', upload_start)
          .delegate('.image_asset_upload', 'upload_errors', upload_errors)
          .delegate('.image_asset_upload', 'upload_start_all', upload_start_all)
          .delegate('.image_asset_upload', 'upload_finished_all', upload_finished_all)
          .delegate('.image_asset_upload', 'change', function(e) {
            $(this).imageUploader();
          });
    }

    // Display images that were already uploaded but not yet saved
    // because of other non-related form errors.
    $('.image_preview_box [name$="unsaved_image_data"]').each(function(i, elem) {
        var $data = $(elem);
        if ($data.val()) {
            $data.parents('.image_preview_box').find('.image img').attr('src', $data.val());
        }
    });
}

function fixPasswordField($context) {
    // This is a hack to prevent password managers from automatically
    // deleting add-ons.  See bug 630126.
    $context.find('input[type="password"]').each(function(){
        var $this = $(this);
        if($this.attr('data-name')) {
            $this.attr('name', $this.attr('data-name'));
        }
    });
    return true;
}

function initSubmit() {
    var dl = $('body').attr('data-default-locale');
    var el = format('#trans-name [lang="{0}"]', dl);
    $(el).attr('id', "id_name");
    $('#submit-describe').delegate(el, 'keyup', slugify)
        .delegate(el, 'blur', slugify)
        .delegate('#edit_slug', 'click', show_slug_edit)
        .delegate('#id_slug', 'change', function() {
            $('#id_slug').attr('data-customized', 1);
            var v = $('#id_slug').val();
            if (!v) {
                $('#id_slug').attr('data-customized', 0);
                slugify();
            }
        });
    $('#id_slug').each(slugify);
    reorderPreviews();
    $('.invisible-upload [disabled]').attr('disabled', false);
    $('.invisible-upload .disabled').removeClass('disabled');
}

function generateErrorList(o) {
    var list = $("<ul class='errorlist'></ul>");
    $.each(o, function(i, v) {
        list.append($(format('<li>{0}</li>', v)));
    });
    return list;
}


function initPayments(delegate) {
  var $delegate = $(delegate || document.body);
    if (z.noEdit) return;
    var previews = [
        'img/zamboni/contributions/passive.png',
        'img/zamboni/contributions/after.png',
        'img/zamboni/contributions/roadblock.png'
    ],
        media_url = $("body").attr("data-media-url"),
        to = false,
        img = $("<img id='contribution-preview'/>");
        moz = $("input[value='moz']");
    img.hide().appendTo($("body"));
    moz.parent().after(
        $("<a class='extra' target='_blank' href='http://www.mozilla.org/foundation/'>"+gettext('Learn more')+"</a>"));
    $(".nag li label").each(function (i,v) {
        var pl = new Image();
        pl.src = media_url + previews[i];
        $(this).after(format(" &nbsp;<a class='extra' href='{0}{1}'>{2}</a>", [media_url, previews[i], gettext('Example')]));
    });
    $(".nag").delegate("a.extra", "mouseover", function(e) {
        var tgt = $(this);
        img.attr("src", tgt.attr("href")).css({
            position: 'absolute',
            'pointer-events': 'none',
            top: tgt.offset().top-350,
            left: ($(document).width()-755)/2
        });
        clearTimeout(to);
        to = setTimeout(function() {
            img.fadeIn(100);
        }, 300);
    }).delegate("a.extra", "mouseout", function(e) {
        clearTimeout(to);
        img.fadeOut(100);
    })
    .delegate("a.extra", "click", function(e) {
        e.preventDefault();
    });
    $("#do-setup").click(_pd(function (e) {
        $("#setup").removeClass("hidden").show();
        $(".intro, .intro-blah").hide();
    }));
    $("#setup-cancel").click(_pd(function (e) {
        $(".intro, .intro-blah").show();
        $("#setup").hide();
    }));
    $("#do-marketplace").click(_pd(function (e) {
        $("#marketplace-confirm").removeClass("hidden").show();
        $(".intro, .intro-blah").hide();
    }));
    $("#marketplace-cancel").click(_pd(function (e) {
        $(".intro, .intro-blah").show();
        $("#marketplace-confirm").hide();
    }));
    $(".recipient").change(function (e) {
        var v = $(this).val();
        $(".paypal").hide(200);
        $(format("#org-{0}", [v])).removeClass("hidden").show(200);
    });
    $("#id_enable_thankyou").change(function (e) {
        if ($(this).attr("checked")) {
            $(".thankyou-note").show().removeClass("hidden");
        } else {
            $(".thankyou-note").hide();
        }
    }).change();
    $delegate.find('#id_text, #id_free').focus(function(e) {
        $delegate.find('#id_do_upsell_1').attr('checked', true);
    });
}

function initCatFields(delegate) {
    var $delegate = $(delegate || '#addon-categories-edit');
    $delegate.find('div.addon-app-cats').each(function() {
        var $parent = $(this).closest("[data-max-categories]"),
            $main = $(this).find(".addon-categories"),
            $misc = $(this).find(".addon-misc-category"),
            maxCats = parseInt($parent.attr("data-max-categories"), 10);
        var checkMainDefault = function() {
            var checkedLength = $("input:checked", $main).length,
                disabled = checkedLength >= maxCats;
            $("input:not(:checked)", $main).attr("disabled", disabled);
            return checkedLength;
        };
        var checkMain = function() {
            var checkedLength = checkMainDefault();
            $("input", $misc).attr("checked", checkedLength <= 0);
        };
        var checkOther = function() {
            $("input", $main).attr("checked", false).attr("disabled", false);
        };
        checkMainDefault();
        $('input', $main).on('change', checkMain);
        $('input', $misc).on('change', checkOther);
    });
}

function initLicenseFields() {
    $("#id_has_eula").change(function (e) {
        if ($(this).attr("checked")) {
            $(".eula").show().removeClass("hidden");
        } else {
            $(".eula").hide();
        }
    });
    $("#id_has_priv").change(function (e) {
        if ($(this).attr("checked")) {
            $(".priv").show().removeClass("hidden");
        } else {
            $(".priv").hide();
        }
    });
    var other_val = $(".license-other").attr("data-val");
    $(".license").click(function (e) {
        if ($(this).val() == other_val) {
            $(".license-other").show().removeClass("hidden");
        } else {
            $(".license-other").hide();
        }
    });
}

function initAuthorFields() {
    // Add the help line after the blank author row.
    $('#what-are-roles').on('click', _pd(function() {
        var overlay = makeOrGetOverlay({});
        overlay.html($('#author-roles-help-template').html())
               .addClass('show');
        overlay.on('click', '.close', _pd(function() {
            overlay.trigger('overlay_dismissed')
        }));
    }))

    if (z.noEdit) return;

    var request = false,
        timeout = false,
        manager = $("#id_form-TOTAL_FORMS"),
        empty_form = template($("#user-form-template").html().replace(/__prefix__/g, "{0}")),
        author_list = $("#author_list");
    author_list.sortable({
        items: ".author",
        handle: ".handle",
        containment: author_list,
        tolerance: "pointer",
        update: renumberAuthors
    });
    addAuthorRow();

    $(".author .errorlist").each(function() {
        $(this).parent()
            .find(".email-autocomplete")
            .addClass("tooltip")
            .addClass("invalid")
            .addClass("formerror")
            .attr("title", $(this).text());
    });

    $("#author_list").delegate(".email-autocomplete", "keypress", validateUser)
    .delegate(".email-autocomplete", "keyup", validateUser)
    .delegate(".remove", "click", function (e) {
        e.preventDefault();
        var tgt = $(this),
            row = tgt.parents("li");
        if (author_list.children(".author:visible").length > 1) {
            if (row.hasClass("initial")) {
                row.find(".delete input").attr("checked", "checked");
                row.hide();
            } else {
                row.remove();
                manager.val(author_list.children(".author").length);
            }
            renumberAuthors();
        }
    });
    function renumberAuthors() {
        author_list.children(".author").each(function(i, el) {
            $(this).find(".position input").val(i);
        });
        if ($(".author:visible").length > 1) {
            author_list.sortable("enable");
            $(".author .remove").show();
            $(".author .handle").css('visibility','visible');
        } else {
            author_list.sortable("disable");
            $(".author .remove").hide();
            $(".author .handle").css('visibility','hidden');
        }
    }
    function addAuthorRow() {
        var numForms = author_list.children(".author").length;
        author_list.append(empty_form([numForms]))
                   .sortable("refresh");
        manager.val(author_list.children(".author").length);
        renumberAuthors();
    }
    function validateUser(e) {
        var tgt = $(this),
            row = tgt.parents("li");
        if (row.hasClass("blank")) {
            tgt.removeClass("placeholder")
               .attr("placeholder", undefined);
            row.removeClass("blank")
               .addClass("author");
            addAuthorRow();
        }
        if (tgt.val().length > 2) {
            if (timeout) clearTimeout(timeout);
            timeout = setTimeout(function() {
                tgt.addClass("ui-autocomplete-loading")
                   .removeClass("invalid")
                   .removeClass("valid");
                request = $.ajax({
                    url: tgt.attr("data-src"),
                    data: {q: tgt.val()},
                    success: function(data) {
                        tgt.removeClass('ui-autocomplete-loading tooltip')
                           .removeClass('formerror')
                           .removeAttr('title')
                           .removeAttr('data-oldtitle');
                        $('#tooltip').hide();
                        if (data.status == 1) {
                            tgt.addClass("valid");
                        } else {
                            tgt.addClass("invalid tooltip formerror")
                               .attr('title', data.message);
                        }
                    },
                    error: function() {
                        tgt.removeClass("ui-autocomplete-loading")
                           .addClass("invalid");
                    }
                });
            }, 500);
        }
    }
}


function imagePoller() {
    this.start = function(override, delay) {
        if (override || !this.poll) {
            this.poll = window.setTimeout(this.check, delay || 1000);
        }
    };
    this.stop = function() {
        window.clearTimeout(this.poll);
        this.poll = null;
    };
}

var imageStatus = {
    start: function(do_icon, do_preview) {
        this.icon = new imagePoller();
        this.imageasset = new imagePoller();
        this.preview = new imagePoller();
        this.icon.check = function() {
            var self = imageStatus,
                node = $('.edit-media, .submit-media');

            // If there are no icons to check, don't check for icons.
            if (!node.length) {
                return;
            }
            $.getJSON(node.attr('data-checkurl'),
                function(json) {
                    if (json !== null && json.icons) {
                        $('.edit-media, .submit-media').find('img').each(function() {
                            var $this = $(this);
                            $this.attr('src', self.newurl($this.attr('src')));
                        });
                        self.icon.stop();
                        self.stopping();
                    } else {
                        self.icon.start(true, 2500);
                        self.polling();
                    }
            });
        };
        this.preview.check = function() {
            var self = imageStatus;
            $('div.preview-thumb').each(function(){
                check_images(this);
            });
            function check_images(el) {
                var $this = $(el);
                if ($this.hasClass('preview-successful')) {
                    return;
                }
                var img = new Image();
                img.onload = function() {
                    $this.removeClass('preview-error preview-unknown').addClass('preview-successful');
                    $this.attr('style', 'background-image:url(' + self.newurl($this.attr('data-url')) + ')');
                    if (!$('div.preview-error').length) {
                        self.preview.stop();
                        self.stopping();
                    }
                };
                img.onerror = function() {
                    setTimeout(function() { check_images(el); }, 2500);
                    self.polling();
                    $this.attr('style', '').addClass('preview-error');
                    delete img;
                };
                img.src = self.newurl($this.attr('data-url'));
            }
        };
        if (do_icon) {
            this.icon.start();
        }
        if (do_preview) {
            this.preview.start();
        }
    },
    polling: function() {
        if (this.icon.poll || this.preview.poll) {
            // I don't want this to show up for submission.
            var node = $('.edit-media');
            if (!node.find('b.image-message').length) {
                $(format('<b class="save-badge image-message">{0}</b>',
                  [gettext('Image changes being processed')]))
                  .appendTo(node.find('h2').first());
            }
            $('#submit-media #icon_preview_64, table #icon_preview_readonly').addClass('loading');
        }
    },
    newurl: function(orig) {
        if (!orig) {
            orig = '';
        }
        var bst = new Date().getTime();
        orig += (orig.indexOf('?') > 1 ? '&' : '?') + bst;
        return orig;
    },
    cancel: function() {
        this.icon.stop();
        this.preview.stop();
        this.stopping();
    },
    stopping: function() {
        if (!this.icon.poll && !this.preview.poll) {
            $('.edit-media b.image-message').remove();
        }
        if (!this.icon.poll) {
            $('#submit-media #icon_preview_64, table #icon_preview_readonly').removeClass('loading');
        }
    }
};

function multipartUpload(form, onreadystatechange) {
    var xhr = new XMLHttpRequest(),
        boundary = "BoUnDaRyStRiNg",
        form = $(form),
        serialized = form.serializeArray(),
        submit_items = [],
        output = "";

    xhr.open("POST", form.attr('action'), true);
    xhr.overrideMimeType('text/plain; charset=x-user-defined-binary');
    xhr.setRequestHeader('Content-length', false);
    xhr.setRequestHeader("Content-Type", "multipart/form-data;" +
                                         "boundary=" + boundary);

    $('input[type="file"]', form).each(function(){
        var files = $(this)[0].files,
            file_field = $(this);

        $.each(files, function(k, file) {
            var data = file.getAsBinary();

            serialized.push({
                'name': $(file_field).attr('name'),
                'value': data,
                'file_type': file.type,
                'file_name': file.name || file.fileName
            });
        });

    });

    $.each(serialized, function(k, v){
        output += "--" + boundary + "\r\n";
        output += "Content-Disposition: form-data; name=\"" + v.name + "\";";

        if (v.file_name !== undefined) {
            output += " filename=\"new-upload\";\r\n";
            output += "Content-Type: " + v.file_type;
        }

        output += "\r\n\r\n";
        output += v.value;
        output += "\r\n";

    });

    output += "--" + boundary + "--";

    if (onreadystatechange) {
        xhr.onreadystatechange = function(e) { onreadystatechange(e, xhr); };
    }

    xhr.sendAsBinary(output);
}

function hideSameSizedIcons() {
    // We don't need this for apps.
    return;
    // icon_sizes = [];
    // $('#icon_preview_readonly img').show().each(function(){
    //     size = $(this).width() + 'x' + $(this).height();
    //     if($.inArray(size, icon_sizes) >= 0) {
    //         $(this).hide();
    //     }
    //     icon_sizes.push(size);
    // });
}


function initTruncateSummary() {
    // If the summary from a manifest is too long, truncate it!
    // EN-US only, since it'll be way too hard to accomodate all languages properly.
    var $submit_describe = $('#submit-describe, #submit-details'),
        $summary = $('textarea[name=summary_en-us]', $submit_describe),
        $desc = $('textarea[name=description_en-us]', $submit_describe);

    if($summary.length && $desc.length) {
        var max_length = parseInt($('.char-count', $submit_describe).attr('data-maxlength'), 10),
            text = $summary.val(),
            submitted = ($('.errorlist li', $submit_describe).length > 0);

        if($desc.val() === '' && text.length > max_length && !submitted) {
            var new_text = text.substr(0, max_length),
                // New line or punctuation followed by a space
                punctuation = new_text.match(/\n|[.?!]\s/g);

            if(punctuation.length) {
                var d = punctuation[punctuation.length - 1];
                new_text = new_text.substr(0, new_text.lastIndexOf(d)+1).trim();
                if(new_text.length > 0) {
                    $desc.val(text);
                    $summary.val(new_text).trigger('keyup');
                }
            }
        }
    }
}

function initInAppConfig($dom) {
    var $appProtocol = $('.inapp-domain-protocol', $dom),
        $chbox = $('#id_is_https', $dom);
    $('#in-app-private-key .generator', $dom).click(_pd(function() {
        var $generator = $(this),
            url = $generator.attr('data-url'),
            $secret = $('#in-app-private-key .secret', $dom);
        $.ajax({type: 'GET',
                url: url,
                success: function(privateKey) {
                    $generator.hide();
                    $secret.show().val(privateKey);
                    // Hide the secret key after 2 minutes.
                    setTimeout(function() {
                        $secret.val('').hide();
                        $generator.show();
                    }, 1000 * 60 * 2);
                },
                error: function(XMLHttpRequest, textStatus, errorThrown) {
                    if (typeof console !== 'undefined') {
                        console.log(XMLHttpRequest, textStatus, errorThrown);
                    }
                },
                dataType: 'text'});
    }));

    function setProtocol() {
        var protocol = $chbox.is(':checked') ? 'https': 'http';
        $appProtocol.text(protocol + '://');
    }

    $chbox.change(function() {
        setProtocol();
    });

    setProtocol();
}

