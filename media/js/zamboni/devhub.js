$(document).ready(function() {
    // Edit Add-on
    $("#edit-addon").exists(initEditAddon);

    //Ownership
    $("#author_list").exists(function() {
        initAuthorFields();
        initLicenseFields();
    });

    //Payments
    $('.payments').exists(initPayments);

    // Edit Versions
    $('.edit-version').exists(initEditVersions);

    // View versions
    $('#version-list').exists(initVersions);

    // Submission process
    $('.addon-submission-process').exists(function(){
        initLicenseFields();
        initCharCount();
        initSubmit();
    });

    // Merchant Account Setup
    $('#id_paypal_id').exists(initMerchantAccount);

    // Validate addon (standalone)
    $('.validate-addon').exists(initSubmit);

    // Add-on Compatibility Check
    $('#addon-compat-upload').exists(initAddonCompatCheck, [$('#addon-compat-upload')]);

    // Submission > Describe
    $("#submit-describe").exists(initCatFields);

    // Submission > Descript > Summary
    $('.addon-submission-process #submit-describe').exists(initTruncateSummary);

    // Submission > Media
    $('#submit-media').exists(function() {
        initUploadIcon();
        initUploadPreview();
    });

    $('.perf-tests').exists(initPerfTests, [window.document]);

    // Add-on uploader
    if($('#upload-addon').length) {
        var opt = {'cancel': $('.upload-file-cancel') };
        if($('#addon-compat-upload').length) {
            opt.appendFormData = function(formData) {
                formData.append('app_id',
                                $('#id_application option:selected').val());
                formData.append('version_id',
                                $('#id_app_version option:selected').val());
            };
        }
        $('#upload-addon').addonUploader(opt);
        $('#id_admin_override_validation').addClass('addon-upload-failure-dependant')
            .change(function () {
                if ($(this).attr('checked')) {
                    // TODO: Disable these when unchecked, or bounce
                    // between upload_errors and upload_success
                    // handlers? I think the latter would mostly be a
                    // bad idea, since failed validation might give us
                    // the wrong results, and admins overriding
                    // validation might need some additional leeway.
                    $('.platform:hidden').show();
                    $('.platform label').removeClass('platform-disabled');
                    $('.addon-upload-dependant').attr('disabled', false);
                } else {
                    $('.addon-upload-dependant').attr('disabled', true);
                }
            });
        $('.addon-upload-failure-dependant').attr('disabled', true);
    }

    if ($(".version-upload").length) {
        $modal = $(".add-file-modal").modal(".version-upload", {
            width: '450px',
            hideme: false,
            callback: function() {
                $('.upload-status').remove();
                return true;
            }
        });

        $('.upload-file-cancel').click(_pd($modal.hideMe));
        $('#upload-file').submit(_pd(function(e) {
            $.ajax({
                url: $(this).attr('action'),
                type: 'post',
                data: $(this).serialize(),
                success: function(response) {
                    if (response.url) {
                        window.location = response.url;
                    }
                },
                error: function(xhr) {
                    var errors = $.parseJSON(xhr.responseText);
                    $("#upload-file").find(".errorlist").remove();
                    $("#upload-file").find(".upload-status").before(generateErrorList(errors));
                    $('#upload-file-finish').attr('disabled', false);
                    $modal.setPos();
                }
            });
        }));
        if (window.location.hash === '#version-upload') {
            $modal.render();
        }
    }

    if($('#upload-webapp-url').exists()) {
        $('#upload-webapp-url').bind("keyup change blur", function(e) {
            var $this = $(this),
                $button = $('#validate_app'),
                // Ensure it's at least "protocol://host/something.(webapp/json)"
                match = $this.val().match(/^(.+):\/\/(.+)\/(.+)\.(webapp|json)$/);

            if($this.attr('data-input') != $this.val()) {
                // Show warning if 8+ characters have been typed but there's no protocol.
                if($this.val().length >= 8 && !$this.val().match(/^(.+):\/\//)) {
                    $('#validate-error-protocol').fadeIn();
                } else {
                    $('#validate-error-protocol').hide();
                }

                // Show the button if valid
                $button.toggleClass('disabled', !match);
                $this.attr('data-input', $this.val());
                $('#upload-status-results').remove();
                $('#upload-file button.upload-file-submit').attr('disabled', true);
            }
        })
        .trigger('keyup')
        .bind('upload_finished', function(e, success, r, message) {
            $('#upload-status-results').remove();
            $('#upload-webapp-url').removeClass('loading');

            var $error_box = $('<div>', {'id': 'upload-status-results', 'class':
                                         'status-' + (success ? 'pass' : 'fail')}).show(),
                $eb_messages = $("<ul>", {'id': 'upload_errors'}),
                messages = r.validation.messages;

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
        })
        .bind('upload_errors', function(e, r) {
            var v = r.validation,
                error_message = format(ngettext(
                    "Your app failed validation with {0} error.",
                    "Your app failed validation with {0} errors.",
                    v.errors), [v.errors]);

            $(this).trigger('upload_finished', [false, r, error_message]);
            $('#validate_app').removeClass('disabled');
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
            $('#upload-file button.upload-file-submit').attr('disabled', false);
        });

        // Add protocol if needed
        $('#validate-error-protocol a').click(_pd(function() {
            var $webapp_url = $('#upload-webapp-url');
            $webapp_url.val($(this).text() + $webapp_url.val());
            $webapp_url.focus().trigger('keyup');
        }));

        $('#validate-field').submit(function() {
            if($('#validate_app').hasClass('disabled')) return false;

            $('#validate_app').addClass('disabled');
            $.post($('#upload-webapp-url').attr('data-upload-url'), {'manifest': $('#upload-webapp-url').val()}, check_webapp_validation);
            $('#upload-webapp-url').addClass('loading');
            return false;
        });
        function check_webapp_validation(results) {
            var $upload_field = $('#upload-webapp-url');
            $('#id_upload').val(results.upload);
            if(! results.validation) {
                setTimeout(function(){
                    $.ajax({
                        url: results.url,
                        dataType: 'json',
                        success: check_webapp_validation,
                        error: function(xhr, textStatus, errorThrown) {
                            /*
                            var errOb = parseErrorsFromJson(xhr.responseText);
                            $upload_field.trigger("upload_errors", [file, errOb.errors, errOb.json]);
                            $upload_field.trigger("upload_finished", [file]);
                            */
                        }
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

    // Jetpack
    if($('#jetpack').exists()) {
        $('a[rel="video-lightbox"]').click(_pd(function() {
            var $this = $(this),
                text = gettext('Your browser does not support the video tag'),
                $overlay = $('<div>', {id: 'jetpack-overlay'}),
                $video = $('<video>', {'controls': 'controls', 'text': text,
                                       'css': {'max-width': $this.attr('data-width') + 'px'}}),
                $src_mp3 = $('<source>', {'type': 'video/mp4; codecs="avc1.42E01E, mp4a.40.2"',
                                          'src': $this.attr('data-mp4') }),
                $src_webm = $('<source>', {'type': 'video/webm; codecs="vp8, vorbis"',
                                           'src': $this.attr('data-webm') }),
                $src_ogv = $('<source>', {'type': 'video/ogv; codecs="theora, vorbis"',
                                          'src': $this.attr('data-ogv') });

            $(window).bind('keydown.lightboxDismiss', function(e) {
                if (e.which == 27) {
                    $overlay.remove();
                    $(window).unbind('keydown.lightboxDismiss');
                }
            });
            $overlay.append($video);
            $video.append($src_mp3);
            $video.append($src_webm);
            $video.append($src_ogv);
            $('body').append($overlay);
            $video[0].play();
            $video.click(function(e){ e.stopPropagation(); });
            $overlay.click(function() {
                $(this).remove();
                $(window).unbind('keydown.lightboxDismiss');
            });
        }));
    }

    $(".invisible-upload a").click(_pd(function() {}));

    // Choosing platform when submitting an Addon and/or files.
    if ($('input.platform').length) {
        initPlatformChooser();
    }

    // when to start and stop image polling
    if ($('#edit-addon-media').length &&
        $('#edit-addon-media').attr('data-checkurl') !== undefined) {
        imageStatus.start();
    }
    $('#edit-addon-media').bind('click', function() {
        imageStatus.cancel();
    });

    // hook up various links related to current version status
    $('#modal-cancel').modal('#cancel-review', {width: 400});
    $('#modal-delete').modal('#delete-addon', {
        width: 400,
        callback: function(obj) {
            return fixPasswordField(this);
        }
    });
    $('#modal-disable').modal('#disable-addon', {
        width: 400,
        callback: function(d){
            $('.version_id', this).val($(d.click_target).attr('data-version'));
            return true;
        }
    });

    // In-app payments config.
    if ($('#in-app-config').length) {
        initInAppConfig($('#in-app-config'));
    }
});

function initUploadControls() {
    /*
    $('.upload-status').removeClass("hidden").hide();
    $('.upload-status').bind('upload-start', function() {
    }).bind('upload-finish', function() {
        $(this).removeClass("ajax-loading");
    });
    $(".invisible-upload").delegate("#upload-file-input", "change", function(e) {
        $('#upload-status-bar').attr('class', '');
        $('#upload-status-text').text("");
        $('#upload-status-results').text("").attr("class", "");
        $('#upload-status-bar div').css('width', 0).show();
        $('#upload-status-bar').removeClass('progress-idle');
        fileUpload($(this), $(this).closest(".invisible-upload").attr('data-upload-url'));
        $('.upload-status').show();
    });
    */
}

function initPlatformChooser() {
    $('input.platform').live('change', function(e) {
        var form = $(this).parents('form'),
            platform = false,
            parent = form,
            val = $(this).val(),
            container = $(this).parents('div:eq(0)');
        $.each(['desktop-platforms', 'mobile-platforms'], function (i, cls) {
            if (container.hasClass(cls)) {
                parent = container;
                return false;
            }
        });
        if (val == '1' || val == '9') {
            // Platform=ALL or Platform=ALL Mobile
            if ($(this).attr('checked')) {
                // Uncheck all other platforms:
                $(format('input.platform:not([value="{0}"])', val),
                  parent).attr('checked', false);
            }
        } else {
            if ($(this).attr('checked')) {
                // Any other platform was checked so uncheck Platform=ALL
                $('input.platform[value="1"],input.platform[value="9"]',
                  parent).attr('checked', false);
            }
        }
    });
}

$(document).ready(function() {
    $.ajaxSetup({cache: false});

    $('.more-actions-popup').each(function() {
      var el = $(this);
      el.popup(el.closest('li').find('.more-actions'), {
        width: 'inherit',
        offset: {x: 15},
        callback: function(obj) {
            return {pointTo: $(obj.click_target)};
        }
      });
    });

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

    initCompatibility();

    $('.addon-edit-cancel').live('click', function(){
        parent_div = $(this).closest('.edit-addon-section');
        parent_div.load($(this).attr('href'), function() {
            hideSameSizedIcons();
            z.refreshL10n();
        });
        if (parent_div.is('#edit-addon-media')) {
            imageStatus.start();
        }
        return false;
    });
});

(function initFormPerms() {
    z.noEdit = $("body").hasClass("no-edit");
    if (z.noEdit) {
        $primary = $(".primary");
        $els = $primary.find("input, select, textarea, button, a.button");
        $els.attr("disabled", "disabled");
        $primary.find("span.handle, a.remove").hide();
        $(".primary h3 a.button").remove();
        $(document).ready(function() {
            $els.unbind().undelegate();
        });
    }
})();

function truncateFields() {
    // TODO (potch) find a good fix for this later
    // as per Bug 622030...
    return;
    // var els = [
    //         "#addon-description",
    //         "#developer_comments"
    //     ];
    // $(els.join(', ')).each(function(i,el) {
    //     var $el = $(el),
    //         originalHTML = $el.html();
    //     $el.delegate("a.truncate_expand", "click", function(e) {
    //         e.preventDefault();
    //         $el.html(originalHTML).css('max-height','none');
    //     })
    //     .vtruncate({
    //         truncText: format("&hellip; <a href='#' class='truncate_expand'>{0}</a>",[gettext("More")])
    //     });
    // });
}


function addonFormSubmit() {
    parent_div = $(this);

    (function(parent_div){
        // If the baseurl changes (the slug changed) we need to go to the new url.
        var baseurl = function(){
            return parent_div.find('#addon-edit-basic').attr('data-baseurl');
        };
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
                if (parent_div.is('#edit-addon-media')) {
                    imageStatus.start();
                    hideSameSizedIcons();
                }
                if ($form.find('#addon-categories-edit').length) {
                    initCatFields();
                }
                if ($form.find('#required-addons').length) {
                    initRequiredAddons();
                }

                if (!hasErrors) {
                    var e = $(format('<b class="save-badge">{0}</b>',
                                     [gettext('Changes Saved')]))
                              .appendTo(parent_div.find('h3').first());
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
    .attr("placeholder", gettext("Enter a new author's email address"));

function initEditAddon() {
    if (z.noEdit) return;

    // Load the edit form.
    $('#edit-addon').delegate('h3 a', 'click', function(e){
        e.preventDefault();

        var a = e.target;
        parent_div = $(a).closest('.edit-addon-section');

        (function(parent_div, a){
            parent_div.find(".item").addClass("loading");
            parent_div.load($(a).attr('data-editurl'), function(){
                if (parent_div.find('#addon-categories-edit').length) {
                    initCatFields();
                }
                if (parent_div.find('#required-addons').length) {
                    initRequiredAddons();
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
    initUploadPreview();
}


function initRequiredAddons() {
    var $req = $('#required-addons');
    if (!$req.length || !$('input.autocomplete', $req).length) {
        return;
    }
    $.zAutoFormset({
        delegate: '#required-addons',
        forms: 'ul.dependencies',
        prefix: 'dependencies',
        hiddenField: 'dependent_addon',
        addedCB: function(emptyForm, item) {
            var f = template(emptyForm)({
                icon: item.icon,
                name: item.name || ''
            });
            // Firefox automatically escapes the contents of `href`, borking
            // the curly braces in the {url} placeholder, so let's do this.
            var $f = $(f);
            $f.find('div a').attr('href', item.url);
            return $f;
        }
    });
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
    $(last).after(last_clone);
    $('#id_files-TOTAL_FORMS').val(parseInt(forms_count, 10) + 1);

    return last;
}

function renumberPreviews() {
    previews = $("#file-list").children(".preview:visible");
    previews.each(function(i, el) {
        $(this).find(".position input").val(i);
    });
    $(previews).find(".handle").toggle(previews.length > 1);
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
        $f = $('#edit-addon-media, #submit-media');

    function upload_start_all(e) {
        // Remove old errors.
        $('.edit-addon-media-screenshot-error').hide();

        // Don't let users submit a form.
        $('.edit-media-button button').attr('disabled', true);
    }

    function upload_finished_all(e) {
        // They can submit again
        $('.edit-media-button button').attr('disabled', false);
    }

    function upload_start(e, file) {
        form = create_new_preview_field();
        forms['form_' + file.instance] = form;

        $(form).show().find('.preview-thumb').addClass('loading')
               .css('background-image', 'url(' + file.dataURL + ')');
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

        $el.find('.edit-previews-text').addClass('error').html("")
                                       .append($error_title)
                                       .append($error_list);
        $el.find(".delete input").attr("checked", "checked");
        renumberPreviews();
    }

    if (z.capabilities.fileAPI) {
        $f.delegate('#screenshot_upload', "upload_finished", upload_finished)
          .delegate('#screenshot_upload', "upload_success", upload_success)
          .delegate('#screenshot_upload', "upload_start", upload_start)
          .delegate('#screenshot_upload', "upload_errors", upload_errors)
          .delegate('#screenshot_upload', "upload_start_all", upload_start_all)
          .delegate('#screenshot_upload', "upload_finished_all", upload_finished_all)
          .delegate('#screenshot_upload', 'change', function(e){
                $(this).imageUploader();
          });
    }

    $("#edit-addon-media, #submit-media").delegate("#file-list .remove", "click", function(e){
        e.preventDefault();
        var row = $(this).closest(".preview");
        row.find(".delete input").attr("checked", "checked");
        row.slideUp(300, renumberPreviews);
    });
}

function initInvisibleUploads() {
    if (!z.capabilities.fileAPI) {
        $('.invisible-upload').addClass('legacy');
    }
}

function initUploadIcon() {
    initInvisibleUploads();

    $('#edit-addon-media, #submit-media').delegate('#icons_default a', 'click', function(e){
        e.preventDefault();

        var $error_list = $('#icon_preview').parent().find(".errorlist"),
            $parent = $(this).closest('li');

        $('input', $parent).attr('checked', true);
        $('#icons_default a.active').removeClass('active');
        $(this).addClass('active');

        $("#id_icon_upload").val("");
        $('#icon_preview').show();

        $('#icon_preview_32 img').attr('src', $('img', $parent).attr('src'));
        $('#icon_preview_64 img').attr('src', $('img',
                $parent).attr('src').replace(/32/, '64'));

        $error_list.html("");
    });

    // Upload an image!
    var $f = $('#edit-addon-media, #submit-media'),

        upload_errors = function(e, file, errors){
            var $error_list = $('#icon_preview').parent().find(".errorlist");
            $.each(errors, function(i, v){
                $error_list.append("<li>" + v + "</li>");
            });
        },

        upload_success = function(e, file, upload_hash) {
            $('#id_icon_upload_hash').val(upload_hash)
            $('#icons_default a.active').removeClass('active');

            $('#icon_preview img').attr('src', file.dataURL);

            $('#icons_default input:checked').attr('checked', false);
            $('input[name="icon_type"][value="'+file.type+'"]', $('#icons_default'))
                    .attr('checked', true);
        },

        upload_start = function(e, file) {
            var $error_list = $('#icon_preview').parent().find(".errorlist");
            $error_list.html("");

            $('.icon_preview img', $f).addClass('loading');

            $('.edit-media-button button').attr('disabled', true);
        },

        upload_finished = function(e) {
            $('.icon_preview img', $f).removeClass('loading');
            $('.edit-media-button button').attr('disabled', false);
        };

    $f.delegate('#id_icon_upload', "upload_success", upload_success)
      .delegate('#id_icon_upload', "upload_start", upload_start)
      .delegate('#id_icon_upload', "upload_finished", upload_finished)
      .delegate('#id_icon_upload', "upload_errors", upload_errors)
      .delegate('#id_icon_upload', 'change', function(e) {
        if (z.capabilities.fileAPI) {
            $(this).imageUploader();
        } else {
            $('#icon_preview').hide();
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

function initVersions() {
    $('#modals').hide();
    var versions;
    $.getJSON($('#version-list').attr('data-stats'),
              function(json){ versions = json; });

    $('#modal-delete-version').modal('.version-delete .remove',
        {width: 400,
         callback: function(d){
            /* This sucks because of ngettext. */
            var version = versions[$(d.click_target).attr('data-version')],
                header = $('h3', this),
                files = $('#del-files', this),
                reviews = $('#del-reviews', this);
            header.text(format(header.attr('data-tmpl'), version));
            files.text(format(ngettext('{files} file', '{files} files',
                                       version.files),
                              version));
            reviews.text(format(ngettext('{reviews} review', '{reviews} reviews',
                                         version.reviews),
                                version));
            $('.version_id', this).val(version.id);
            return true;
        }});

    $('#upload-file-finish').click(function() {
        var $button = $(this);
        setTimeout(function() { // Chrome fix
            $button.attr('disabled', true);
        }, 50);
    });

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
    $('.invisible-upload [disabled]').attr("disabled", false);
    $('.invisible-upload .disabled').removeClass("disabled");
}

function generateErrorList(o) {
    var list = $("<ul class='errorlist'></ul>");
    $.each(o, function(i, v) {
        list.append($(format("<li>{0}</li>", v)));
    });
    return list;
}

function initEditVersions() {
    if (z.noEdit) return;
    // Modal box
    $modal = $(".add-file-modal").modal(".add-file", {
        width: '450px',
        hideme: false,
        callback: function() {
            $('.upload-status').remove();
            return true;
        }
    });

    // Handle uploader events
    /*
    $('.upload-status').bind('upload-success', function(e,json) {
        $("#upload-file-finish").attr("disabled", false);
        $modal.setPos();
        $("#id_upload").val(json.upload);
    }).bind('upload-error', function() {
        $modal.setPos(); // Reposition since the error report has been added.
        $("#upload-file-finish").attr("disabled", true);
    });
    */

    $('.upload-file-cancel').click(_pd($modal.hideMe));

    $("#upload-file-finish").click(function (e) {
        e.preventDefault();
        $tgt = $(this);
        if ($tgt.attr("disabled")) return;
        $.ajax({
            url: $("#upload-file").attr("action"),
            type: 'post',
            data: $("#upload-file").serialize(),
            success: function (resp) {
                $("#file-list tbody").append(resp);
                var new_total = $("#file-list tr").length / 2;
                $("#id_files-TOTAL_FORMS").val(new_total);
                $("#id_files-INITIAL_FORMS").val(new_total);
                $modal.hideMe();
            },
            error: function(xhr) {
                var errors = $.parseJSON(xhr.responseText);
                $("#upload-file").find(".errorlist").remove();
                $("#upload-file").find(".upload-status").before(generateErrorList(errors));
                $modal.setPos();
            }
        });
    });

    $("#file-list").delegate("a.remove", "click", function() {
        var row = $(this).closest("tr");
        $("input:first", row).attr("checked", true);
        row.hide();
        row.next().show();
    });

    $("#file-list").delegate("a.undo", "click", function() {
        var row = $(this).closest("tr").prev();
        $("input:first", row).attr("checked", false);
        row.show();
        row.next().hide();
    });

    $('.show_file_history').click(_pd(function(){
        $(this).closest('p').hide().closest('div').find('.version-comments').fadeIn();
    }));

}

function initPayments(delegate) {
  var $delegate = $(delegate || document.body);
    if (z.noEdit) return;
    var previews = [
        "img/zamboni/contributions/passive.png",
        "img/zamboni/contributions/after.png",
        "img/zamboni/contributions/roadblock.png",
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
        $('input', $main).live('change', checkMain);
        $('input', $misc).live('change', checkOther);
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
    $('#author-roles-help').popup('#what-are-roles', {pointTo: $('#what-are-roles') });

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
        author_list.find(".blank .email-autocomplete")
                   .placeholder();
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


function initCompatibility() {
    $('p.add-app a').live('click', _pd(function(e) {
        var outer = $(this).closest('form');

        $('tr.app-extra', outer).each(function() {
            addAppRow(this);
        });

        $('.new-apps', outer).toggle();

        $('.new-apps ul').delegate('a', 'click', _pd(function(e) {
            var $this = $(this),
                sel = format('tr.app-extra td[class="{0}"]', [$this.attr('class')]),
                $row = $(sel, outer);
            $row.parents('tr.app-extra').find('input:checkbox')
                .removeAttr('checked').closest('tr').removeClass('app-extra');
            $this.closest('li').remove();
            if (!$('tr.app-extra', outer).length) {
                $('p.add-app', outer).hide();
            }
        }));
    }));


    $('.compat-versions .remove').live('click', _pd(function(e) {
        var $this = $(this),
            $row = $this.closest('tr');
        $row.addClass('app-extra');
        if (!$row.hasClass('app-extra-orig')) {
            $row.find('input:checkbox').attr('checked', true);
        }
        $('p.add-app:hidden', $this.closest('form')).show();
        addAppRow($row);
    }));

    $('.compat-update-modal').modal('a.compat-update', {
        delegate: $('.item-actions'),
        hideme: false,
        emptyme: true,
        callback: compatModalCallback
    });

    $('.compat-error-popup').popup('a.compat-error', {
        delegate: $('.item-actions'),
        emptyme: true,
        width: '450px',
        callback: function(obj) {
            var $popup = this,
                ct = $(obj.click_target),
                error_url = ct.attr('data-errorurl');

            if (ct.hasClass('ajax-loading'))
                return;
            ct.addClass('ajax-loading');
            $popup.load(error_url, function(e) {
                ct.removeClass('ajax-loading');
            });

            $('.compat-update-modal').modal('a.compat-update', {
                delegate: $('.compat-error-popup'),
                hideme: false,
                emptyme: true,
                callback: compatModalCallback
            });

            return {pointTo: $(obj.click_target)};
        }
    });
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
};

var imageStatus = {
    start: function() {
        this.icon = new imagePoller();
        this.preview = new imagePoller();
        this.icon.check = function() {
            var self = imageStatus,
                node = $('#edit-addon-media');
            $.getJSON(node.attr('data-checkurl'),
                function(json) {
                    if (json !== null && json.icons) {
                        $('#edit-addon-media').find('img').each(function() {
                            $(this).attr('src', self.newurl($(this).attr('src')));
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
                    setTimeout(function(){ check_images(el) }, 2500);
                    self.polling();
                    $this.attr('style', '').addClass('preview-error');
                    delete img;
                };
                img.src = self.newurl($this.attr('data-url'));
            }
        };
        this.icon.start();
        this.preview.start();
    },
    polling: function() {
        if (this.icon.poll || this.preview.poll) {
            var node = $('#edit-addon-media');
            if (!node.find('b.image-message').length) {
                $(format('<b class="save-badge image-message">{0}</b>',
                  [gettext('Image changes being processed')]))
                  .appendTo(node.find('h3').first());
            }
        }
    },
    newurl: function(orig) {
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
            $('#edit-addon-media').find('b.image-message').remove();
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

    xhr.open("POST", form.attr('action'), true)
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

        if(v.file_name != undefined) {
            output += " filename=\"new-upload\";\r\n";
            output += "Content-Type: " + v.file_type;
        }

        output += "\r\n\r\n";
        output += v.value;
        output += "\r\n";

    });

    output += "--" + boundary + "--";

    if(onreadystatechange) {
        xhr.onreadystatechange = function(e){ onreadystatechange(e, xhr); }
    }

    xhr.sendAsBinary(output);
}

function hideSameSizedIcons() {
    icon_sizes = [];
    $('#icon_preview_readonly img').show().each(function(){
        size = $(this).width() + 'x' + $(this).height();
        if($.inArray(size, icon_sizes) >= 0) {
            $(this).hide();
        }
        icon_sizes.push(size);
    });
}


function addAppRow(obj) {
    var outer = $(obj).closest('form'),
        appClass = $('td.app', obj).attr('class');
    if (!$('.new-apps ul', outer).length) {
        $('.new-apps', outer).html('<ul></ul>');
    }
    var sel = format('.new-apps ul a[class="{0}"]', [appClass]);
    if (!$(sel, outer).length) {
        // Append app to <ul> if it's not already listed.
        var appLabel = $('td.app', obj).text(),
            appHTML = '<li><a href="#" class="' + appClass + '">' + appLabel + '</a></li>';
        $('.new-apps ul', outer).append(appHTML);
    }
}


function compatModalCallback(obj) {
    var $widget = this,
        ct = $(obj.click_target),
        form_url = ct.attr('data-updateurl');

    if ($widget.hasClass('ajax-loading'))
        return;
    $widget.addClass('ajax-loading');
    $widget.load(form_url, function(e) {
        $widget.removeClass('ajax-loading');
    });

    $('form.compat-versions').live('submit', function(e) {
        e.preventDefault();
        $widget.empty();

        if ($widget.hasClass('ajax-loading'))
            return;
        $widget.addClass('ajax-loading');

        var widgetForm = $(this);
        $.post(widgetForm.attr('action'), widgetForm.serialize(), function(data) {
            $widget.removeClass('ajax-loading');
            if ($(data).find('.errorlist').length) {
                $widget.html(data);
            } else {
                var c = $('.item[data-addonid=' + widgetForm.attr('data-addonid') + '] .item-actions li.compat');
                c.load(c.attr('data-src'));
                $widget.hideMe();
            }
        });
    });

    return {pointTo: ct};
}

function initAddonCompatCheck($doc) {
    var $elem = $('#id_application', $doc),
        $form = $doc.closest('form');

    $elem.change(function(e) {
        var $appVer = $('#id_app_version', $form),
            $sel = $(e.target),
            appId = $('option:selected', $sel).val();

        if (!appId) {
            $('option', $appVer).remove();
            $appVer.append(format('<option value="{0}">{1}</option>',
                                  ['', gettext('Select an application first')]));
            return;
        }
        $.post($sel.attr('data-url'),
               {application_id: appId,
                csrfmiddlewaretoken: $("input[name='csrfmiddlewaretoken']", $form).val()},
            function(d) {
                $('option', $appVer).remove();
                $.each(d.choices, function(i, ch) {
                    $appVer.append(format('<option value="{0}">{1}</option>',
                                          [ch[0], ch[1]]));
                });
            });
    });

    if ($elem.children('option:selected').val() &&
        !$('#id_app_version option:selected', $form).val()) {
        // If an app is selected when page loads and it's not a form post.
        $elem.trigger('change');
    }
}

function initPerfTests(doc) {
    $('.perf-test-listing .start-perf-tests', doc).click(function(ev) {
        var $start = $(ev.target),
            start_url = $start.attr('href'),
            $results = $('.perf-results', $start.closest('ul'));
        ev.preventDefault();
        $results.text(gettext('Starting tests...'));
        $.ajax({type: 'GET',
                url: start_url,
                success: function(data) {
                    // TODO(Kumar) poll for results and display message
                    $results.attr('data-got-response', 1);
                    if (data.success) {
                        $results.text(gettext('Waiting for test results...'));
                    } else {
                        $results.text(gettext('Internal Server Error'));
                    }
                },
                error: function(XMLHttpRequest, textStatus, errorThrown) {
                    $results.attr('data-got-response', 1);
                    $results.text(gettext('Internal Server Error'));
                },
                dataType: 'json'});
    });
}

function initMerchantAccount() {
    var ajax = false,
        $paypal_field = $('#id_paypal_id'),
        $paypal_verify = $('#paypal-id-verify'),
        $paypal_support = $('#id_support_email'),
        current = $paypal_field.val(),
        keyup = true;

    $paypal_field.bind('keyup', function(e) {
        if($paypal_field.val() != current) {
            if(ajax) {
                ajax.abort();
            }
            $paypal_verify.removeAttr('class');
            keyup = true;
        }
        current = $paypal_field.val();
    }).blur(function() {
        // `keyup` makes sure we don't re-fetch without changes.
        if(! keyup || current == "") return;
        keyup = false;

        if(ajax) {
            ajax.abort();
        }
        $paypal_verify.attr('class', 'pp-unknown');

        if(!$paypal_field.val().match(/.+@.+\..+/)) {
            $paypal_verify.attr('class', 'pp-error');
            $('#paypal-id-error').text(gettext('Must be a valid e-mail address.'));
            return;
        }

        // Update support email to match
        if(!$paypal_support.val() || $paypal_support.data('auto')) {
          $paypal_support.val($paypal_field.val());
          $paypal_support.data('auto', true);
        }

        ajax = $.post($paypal_verify.attr('data-url'), {'email': $paypal_field.val()}, function(d) {
            $paypal_verify.attr('class', d.valid ? 'pp-success' : 'pp-error');
            $('#paypal-id-error').text(d.message);
        });
    }).trigger('blur');

    // If support has been changed, don't auto-fill
    $('#id_support_email').change(function() {
      $('#id_support_email').data('auto', false);
    });
}

function initTruncateSummary() {
    // If the summary from a manifest is too long, truncate it!
    // EN-US only, since it'll be way too hard to accomodate all languages properly.
    var $submit_describe = $('#submit-describe'),
        $summary = $('textarea[name=summary_en-us]', $submit_describe),
        $desc = $('textarea[name=description_en-us]', $submit_describe);

    if($summary.length && $desc.length) {
        var max_length = parseInt($('.char-count', $submit_describe).attr('data-maxlength'), 10),
            text = $summary.val(),
            submitted = ($('.errorlist li', $submit_describe).length > 0);

        if($desc.val() == "" && text.length > max_length && !submitted) {
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
}
