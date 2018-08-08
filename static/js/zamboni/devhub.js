$(document).ready(function() {

    // Modals
    var $modalFile, $modalDelete, $modalDisable;

    // Edit Add-on
    $("#edit-addon").exists(initEditAddon);

    //Ownership
    $("#author_list").exists(function() {
        initAuthorFields();
        initLicenseFields();
    });

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

    // Validate addon (standalone)
    $('.validate-addon').exists(initSubmit);

    // Add-on Compatibility Check
    $('#addon-compat-upload').exists(initAddonCompatCheck, [$('#addon-compat-upload')]);

    // Submission > Source
    $("#submit-source").exists(initSourceSubmitOutcomes);

    // Submission > Describe
    $("#submit-describe").exists(initCatFields);
    $("#submit-describe").exists(initCCLicense);

    // Submission > Descript > Summary
    $('.addon-submission-process #submit-describe').exists(initTruncateSummary);

    // Submission > Media
    $('#submit-media').exists(function() {
        initUploadIcon();
        initUploadPreview();
    });

    // Add-on uploader
    var $uploadAddon = $('#upload-addon');
    if ($('#upload-addon').length) {
        var opt = {'cancel': $('.upload-file-cancel') };
        if($('#addon-compat-upload').length) {
            opt.appendFormData = function(formData) {
                formData.append('app_id',
                                $('#id_application option:selected').val());
                formData.append('version_id',
                                $('#id_app_version option:selected').val());
            };
        }
        $uploadAddon.addonUploader(opt);
    }

    if ($(".add-file-modal").length) {
        $modalFile = $(".add-file-modal").modal(".version-upload", {
            width: '450px',
            hideme: false,
            callback: function() {
                $('.upload-status').remove();
                $('.binary-source').hide();
                return true;
            }
        });

        $('.upload-file-cancel').click(_pd($modalFile.hideMe));
        $('#upload-file').submit(_pd(function(e) {
            $('#upload-file-finish').prop('disabled', true);
            $.ajax({
                url: $(this).attr('action'),
                type: 'post',
                data: new FormData(this),
                processData: false,
                contentType: false,
                success: function(response) {
                    if (response.url) {
                        window.location = response.url;
                    }
                },
                error: function(xhr) {
                    var errors = JSON.parse(xhr.responseText);
                    $("#upload-file").find(".errorlist").remove();
                    $("#upload-file").find(".upload-status").before(generateErrorList(errors));
                    $('#upload-file-finish').prop('disabled', false);
                    $modalFile.setPos();
                }
            });
        }));
        if (window.location.hash === '#version-upload') {
            $modalFile.render();
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

            $(window).on('keydown.lightboxDismiss', function(e) {
                if (e.which == 27) {
                    $overlay.remove();
                    $(window).off('keydown.lightboxDismiss');
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
                $(window).off('keydown.lightboxDismiss');
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
    $('#edit-addon-media').on('click', function() {
        imageStatus.cancel();
    });

    // hook up various links related to current version status
    $('#modal-cancel').modal('#cancel-review', {width: 400});
    if ($("#modal-delete").length) {
        $modalDelete = $('#modal-delete').modal('.delete-addon', {
            width: 400,
            callback: function(obj) {
                return fixPasswordField(this);
            }
        });
        if (window.location.hash === '#delete-addon') {
            $modalDelete.render();
        }
    }
    if ($("#modal-disable").length) {
        $modalDisable = $('#modal-disable').modal('.disable-addon', {
            width: 400,
            callback: function(d){
                $('.version_id', this).val($(d.click_target).attr('data-version'));
                return true;
            }
        });
        if (window.location.hash === '#disable-addon') {
            $modalDisable.render();
        }
    }
    if ($("#modal-unlist").length) {
        $modalUnlist = $('#modal-unlist').modal('.unlist-addon', {
            width: 400
        });
        if (window.location.hash === '#unlist-addon') {
            $modalUnlist.render();
        }
    }
    // Show a confirmation modal for forms that have [data-confirm="selector"].
    // This is specifically used for the request full review form for unlisted
    // add-ons.
    $(document.body).on('submit', '[data-confirm]', function(e) {
        e.preventDefault();
        var $form = $(e.target);
        var $modal = $form.data('modal');
        if (!$modal) {
            $modal = $($form.data('confirm')).modal();
            $form.data('modal', $modal);
        }
        $modal.render();
        $modal.on('click', '.cancel', function(e) {
            e.preventDefault();
            e.stopPropagation();
            $modal.trigger('close');
        });
        $modal.on('submit', 'form', function(e) {
            e.preventDefault();
            $form.removeAttr('data-confirm');
            $form.submit();
        });
    });

    $('.enable-addon').on('click', function() {
        $.ajax({
            'type': 'POST',
            'url': $(this).data('url'),
            'success': function() {
                window.location.reload();
            }
        });
    });

    // API credentials page
    $('.api-credentials').on('submit', function() {
        // Disallow double-submit. Don't actually disable the buttons, because
        // then the correct one would not be submitted, but set the class to
        // emulate that.
        $(this).find('button').addClass('disabled');
    });
});

function initPlatformChooser() {
    $(document).on('change', 'input.platform', function(e) {
        var form = $(this).parents('form'),
            platform = false,
            parent = form,
            val = $(this).val(),
            container = $(this).parents('div:eq(0)');
        if (val == '1') {
            // Platform=ALL
            if ($(this).prop('checked')) {
                // Uncheck all other platforms:
                $(format('input.platform:not([value="{0}"])', val),
                  parent).prop('checked', false);
            }
        } else {
            if ($(this).prop('checked')) {
                // Any other platform was checked so uncheck Platform=ALL
                $('input.platform[value="1"]',
                  parent).prop('checked', false);
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
        el.modal(el.siblings('.delete-addon'), {
            width: 400,
            callback: function(obj) {
                fixPasswordField(this);
                return {pointTo: $(obj.click_target)};
            }
        });
    });

    truncateFields();

    initCompatibility();

    $(document).on('click', '.addon-edit-cancel', function(){
        parent_div = $(this).closest('.edit-addon-section');
        parent_div.load($(this).attr('href'), function() {
            $('.tooltip').tooltip('#tooltip');
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
        $els.prop("disabled", true);
        $primary.find("span.handle, a.remove").hide();
        $(".primary h3 a.button").remove();
        $(document).ready(function() {
            $els.off().off();
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
    //     $el.on("click", "a.truncate_expand", function(e) {
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
        $('.edit-media-button button').prop('disabled', false);
        $('form', parent_div).submit(function(e){
            e.preventDefault();
            var old_baseurl = baseurl();
            parent_div.find(".item").removeClass("loaded").addClass("loading");
            var $document = $(document),
                scrollBottom = $document.height() - $document.scrollTop(),
                $form = $(this);

            $.post($form.attr('action'), $form.serialize(), function(d) {
                parent_div.html(d).each(addonFormSubmit);
                // The HTML has changed after we posted the form, thus the need to retrieve the new HTML
                $form = parent_div.find('form');
                var hasErrors = $form.find('.errorlist').length;
                $('.tooltip').tooltip('#tooltip');
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
    $('#edit-addon').on('click', 'h3 a', function(e){
        e.preventDefault();

        var a = e.target;
        parent_div = $(a).closest('.edit-addon-section');

        (function(parent_div, a){
            parent_div.find(".item").addClass("loading");
            parent_div.load($(a).attr('data-editurl'), function(){
                $('.tooltip').tooltip('#tooltip');
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
                icon: item.icons['32'],
                name: _.escape(item.name) || ''
            });
            // Firefox automatically escapes the contents of `href`, borking
            // the curly braces in the {url} placeholder, so let's do this.
            // Note: the trim removes the leading space from the template
            // output so that jquery 1.9 treats it as HTML not a selector.
            var $f = $(f.trim());
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
        $('.edit-media-button button').prop('disabled', true);
    }

    function upload_finished_all(e) {
        // They can submit again
        $('.edit-media-button button').prop('disabled', false);
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
        $el.find(".delete input").prop("checked", true);
        renumberPreviews();
    }

    if (z.capabilities.fileAPI) {
        $f.on("upload_finished", '#screenshot_upload', upload_finished)
          .on("upload_success", '#screenshot_upload', upload_success)
          .on("upload_start", '#screenshot_upload', upload_start)
          .on("upload_errors", '#screenshot_upload', upload_errors)
          .on("upload_start_all", '#screenshot_upload', upload_start_all)
          .on("upload_finished_all", '#screenshot_upload', upload_finished_all)
          .on('change', '#screenshot_upload', function(e){
                $(this).imageUploader();
          });
    }

    $("#edit-addon-media, #submit-media").on("click", "#file-list .remove", function(e){
        e.preventDefault();
        var row = $(this).closest(".preview");
        row.find(".delete input").prop("checked", true);
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

    $('#edit-addon-media, #submit-media').on('click', '#icons_default a', function(e){
        e.preventDefault();

        var $error_list = $('#icon_preview').parent().find(".errorlist"),
            $parent = $(this).closest('li');

        $('input', $parent).prop('checked', true);
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
            $('#id_icon_upload_hash').val(upload_hash);
            $('#icons_default a.active').removeClass('active');

            $('#icon_preview img').attr('src', file.dataURL);

            $('#icons_default input:checked').prop('checked', false);
            $('input[name="icon_type"][value="'+file.type+'"]', $('#icons_default'))
                    .prop('checked', true);
        },

        upload_start = function(e, file) {
            var $error_list = $('#icon_preview').parent().find(".errorlist");
            $error_list.html("");

            $('.icon_preview img', $f).addClass('loading');

            $('.edit-media-button button').prop('disabled', true);
        },

        upload_finished = function(e) {
            $('.icon_preview img', $f).removeClass('loading');
            $('.edit-media-button button').prop('disabled', false);
        };

    $f.on("upload_success", '#id_icon_upload', upload_success)
      .on("upload_start", '#id_icon_upload', upload_start)
      .on("upload_finished", '#id_icon_upload', upload_finished)
      .on("upload_errors", '#id_icon_upload', upload_errors)
      .on('change', '#id_icon_upload', function(e) {
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
            var el = $(d.click_target),
                version = versions[el.data('version')],
                is_current = el.data('is-current') === 1,
                header = $('h3', this),
                files = $('#del-files', this),
                reviews = $('#del-reviews', this);
            header.text(format(header.attr('data-tmpl'), version));
            files.text(format(ngettext('{files} file', '{files} files',
                                       version.files),
                              version));
            reviews.text(format(ngettext('{reviews} user review', '{reviews} user reviews',
                                         version.reviews),
                                version));
            $('.version_id', this).val(version.id);
            $('.current-version-warning', this).toggle(is_current);
            return true;
        }});

    function addToReviewHistory(json, historyContainer, reverseOrder) {
        var empty_note = historyContainer.children('.review-entry-empty');
        json.forEach(function(note) {
            var clone = empty_note.clone(true, true);
            clone.attr('class', 'review-entry');
            if (note["highlight"] == true) {
                clone.addClass("new");
            }
            clone.find('span.action')[0].textContent = note["action_label"];
            var user = clone.find('a:contains("$user_name")');
            user[0].textContent = note["user"]["name"];
            user.attr('href', note["user"]["url"]);
            var date = clone.find('time.timeago');
            date[0].textContent = note["date"];
            date.attr('datetime', note["date"]);
            date.attr('title', note["date"]);
            clone.find('pre:contains("$comments")')[0].textContent = note["comments"];
            if (reverseOrder) {
                historyContainer.append(clone)
            } else {
                clone.insertAfter(historyContainer.children('.review-entry-failure'));
            }
        });
        $("time.timeago").timeago("updateFromDOM");
    }

    function loadReviewHistory(div, nextLoad) {
        div.removeClass("hidden");
        replybox = div.children('.dev-review-reply')
        if (replybox.length == 1) {
            replybox[0].scrollIntoView(false);
        }
        var token = div.data('token');
        var container = div.children('.history-container');
        container.children('.review-entry-loading').removeClass("hidden");
        container.children('.review-entry-failure').addClass("hidden");
        if (!nextLoad) {
            container.children('.review-entry').remove();
            var api_url = div.data('api-url');
        } else {
            var api_url = div.data('next-url');
        }
        var success = function (json) {
            addToReviewHistory(json["results"], container)
            var loadmorediv = container.children('div.review-entry-loadmore');
            if (json["next"]) {
                loadmorediv.removeClass("hidden");
                container.prepend(loadmorediv);
                div.attr('data-next-url', json["next"]);
            } else {
                loadmorediv.addClass("hidden");
            }
        }
        var fail =  function(xhr) {
            container.children('.review-entry-failure').removeClass("hidden");
            container.children('.review-entry-failure').append(
                "<pre>"+api_url+", "+xhr.statusText+", "+xhr.responseText+"</pre>")
        }
        $.ajax({
            url: api_url,
            type: 'get',
            beforeSend: function (xhr) {
                xhr.setRequestHeader ("Authorization", 'Bearer '+token)
            },
            complete: function (xhr) {
                container.children('.review-entry-loading').addClass("hidden")
            },
            processData: false,
            contentType: false,
            success: success,
            error: fail
        });
    }
    $('.review-history-show').click(function (e) {
        e.preventDefault();
        var version = $(this).data('version')
        var $show_link = $('#review-history-show-' + version);
        $show_link.addClass("hidden");
        $show_link.next().removeClass("hidden");
        loadReviewHistory($($show_link.data('div')));
    });
    $('.review-history-hide').click(function (e) {
        e.preventDefault();
        var $tgt = $(this);
        $tgt.addClass("hidden");
        var prev = $tgt.prev();
        prev.removeClass("hidden");
        $(prev.data('div')).addClass("hidden");
    });
    $('a.review-history-loadmore').click(function (e) {
        e.preventDefault();
        var $tgt = $(this);
        loadReviewHistory($($tgt.data('div')), true);
    });
    $('.review-history-hide').prop("style", "");
    $('.review-history.hidden').prop("style", "");
    $('.history-container .hidden').prop("style", "");
    $("time.timeago").timeago();

    $(".dev-review-reply-form").submit(function (e) {
        e.preventDefault();
        $replyForm = $(e.target)
        if ($replyForm.children('textarea').val() == '') {
            return false
        }
        var submitButton = $replyForm.children('button')
        $.ajax({
            type: 'POST',
            url: $replyForm.attr('action'),
            data: $replyForm.serialize(),
            beforeSend: function (xhr) {
                submitButton.prop('disabled', true)
                var token = $replyForm.data('token');
                xhr.setRequestHeader ("Authorization", 'Bearer '+token);
            },
            success: function(json) {
                var historyDiv = $($replyForm.data('history'))
                var container = historyDiv.children('.history-container');
                addToReviewHistory([json], container, true)
                $replyForm.children('textarea').val('')
            },
            complete: function() {
                submitButton.prop('disabled', false)
            },
            dataType: 'json'
        });
        return false;
    });
}

function initSubmit() {
    var dl = $('body').attr('data-default-locale');
    var el = format('#trans-name [lang="{0}"]', dl);
    $(el).attr('id', "id_name");
    $('#submit-describe').on('keyup', el, slugify)
        .on('blur', el, slugify)
        .on('click', '#edit_slug', show_slug_edit)
        .on('change', '#id_slug', function() {
            $('#id_slug').attr('data-customized', 1);
            var v = $('#id_slug').val();
            if (!v) {
                $('#id_slug').attr('data-customized', 0);
                slugify();
            }
        });
    $('#id_slug').each(slugify);
    reorderPreviews();
    $('.invisible-upload [disabled]').prop("disabled", false);
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
    if ($(".add-file-modal").length) {
        var $modal = $(".add-file-modal").modal(".add-file", {
            width: '450px',
            hideme: false,
            callback: function() {
                $('.upload-status').remove();
                return true;
            }
        });

        $('.upload-file-cancel').click(_pd($modal.hideMe));

        $("#upload-file-finish").click(function (e) {
            e.preventDefault();
            $tgt = $(this);
            if ($tgt.prop("disabled")) return;
            $.ajax({
                url: $("#upload-file").attr("action"),
                type: 'post',
                data: new FormData($("#upload-file")[0]),
                processData: false,
                contentType: false,
                success: function (resp) {
                    $("#file-list tbody").append(resp);
                    var new_total = $("#file-list tr").length / 2;
                    $("#id_files-TOTAL_FORMS").val(new_total);
                    $("#id_files-INITIAL_FORMS").val(new_total);
                    $modal.hideMe();
                },
                error: function(xhr) {
                    var errors = JSON.parse(xhr.responseText);
                    $("#upload-file").find(".errorlist").remove();
                    $("#upload-file").find(".upload-status").before(generateErrorList(errors));
                    $modal.setPos();
                }
            });
        });
    }

    $("#file-list").on("click", "a.remove", function() {
        var row = $(this).closest("tr");
        $("input:first", row).prop("checked", true);
        row.hide();
        row.next().show();
    });

    $("#file-list").on("click", "a.undo", function() {
        var row = $(this).closest("tr").prev();
        $("input:first", row).prop("checked", false);
        row.show();
        row.next().hide();
    });

    $('.show_file_history').click(_pd(function(){
        $(this).closest('p').hide().closest('div').find('.version-comments').fadeIn();
    }));

}

function initCatFields(delegate) {
    var $delegate = $(delegate || '#addon-categories-edit');
    $delegate.find('div.addon-app-cats').each(function() {
        var main_selector = ".addon-categories",
            misc_selector = ".addon-misc-category"
        var $parent = $(this);
        var $grand_parent = $(this).closest("[data-max-categories]"),
            $main = $parent.find(main_selector),
            $misc = $parent.find(misc_selector),
            maxCats = parseInt($grand_parent.attr("data-max-categories"), 10);
        var checkMainDefault = function() {
            var checkedLength = $("input:checked", $main).length,
                disabled = checkedLength >= maxCats;
            $("input:not(:checked)", $main).prop("disabled", disabled);
            return checkedLength;
        };
        var checkMain = function() {
            var checkedLength = checkMainDefault();
            $("input", $misc).prop("checked", checkedLength <= 0);
        };
        var checkOther = function() {
            $("input", $main).prop("checked", false).prop("disabled", false);
        };
        checkMainDefault();
        $parent.on('change', main_selector + ' input', checkMain);
        $parent.on('change', misc_selector + ' input', checkOther);
    });
}

function initLicenseFields() {
    $("#id_has_eula").change(function (e) {
        if ($(this).prop("checked")) {
            $(".eula").show().removeClass("hidden");
        } else {
            $(".eula").hide();
        }
    });
    $("#id_has_priv").change(function (e) {
        if ($(this).prop("checked")) {
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

    $("#author_list")
        .on("keypress", ".email-autocomplete", validateUser)
        .on("keyup", ".email-autocomplete", validateUser)
        .on("click", ".remove", function (e) {
            e.preventDefault();
            var tgt = $(this),
                row = tgt.parents("li");
            if (author_list.children(".author:visible").length > 1) {
                if (row.hasClass("initial")) {
                    row.find(".delete input").prop("checked", true);
                    row.hide();
                } else {
                    row.remove();
                    manager.val(author_list.children(".author").length);
                }
                renumberAuthors();
            }
        });


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
    }

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
}


function initCompatibility() {
    $(document).on('click', 'p.add-app a', _pd(function(e) {
        var outer = $(this).closest('form');

        $('tr.app-extra', outer).each(function() {
            addAppRow(this);
        });

        $('.new-apps', outer).toggle();

        $('.new-apps ul').on('click', 'a', _pd(function(e) {
            var $this = $(this),
                sel = format('tr.app-extra td[class="{0}"]', [$this.attr('class')]),
                $row = $(sel, outer);
            $row.parents('tr.app-extra').find('input:checkbox')
                .prop('checked', false).closest('tr').removeClass('app-extra');
            $this.closest('li').remove();
            if (!$('tr.app-extra', outer).length) {
                $('p.add-app', outer).hide();
            }
        }));
    }));


    $(document).on('click', '.compat-versions .remove', _pd(function(e) {
        var $this = $(this),
            $row = $this.closest('tr');
        $row.addClass('app-extra');
        if (!$row.hasClass('app-extra-orig')) {
            $row.find('input:checkbox').prop('checked', true);
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
}

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
                    setTimeout(function() {
                        check_images(el);
                    }, 2500);
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

    $(document).on('submit', 'form.compat-versions', function(e) {
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
               {application: appId,
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

        if($desc.val() === "" && text.length > max_length && !submitted) {
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

function initCCLicense() {

    function setCopyright(isCopyr) {
        // Set the license options based on whether the copyright license is selected.
        if (isCopyr) {
            $('.noncc').addClass('disabled');
            // Choose "No" and "No" for the "commercial" and "derivative" questions.
            $('input[name="cc-noncom"][value=1], input[name="cc-noderiv"][value=2]').prop('checked', true);
        } else {
            $('.noncc').removeClass('disabled');
        }
    }
    function setLicenseFromWizard() {
        var cc_data = $('input[name^="cc-"]:checked').map(function() {
            return this.dataset.cc;}).get();
        var radio = $('#submit-describe #license-list input[type=radio][data-cc="' + cc_data.join(' ') + '"]');
        if (radio.length) {
            radio.prop('checked', true);
            return radio;
        }
        cc_data.pop();
        radio = $('#submit-describe #license-list input[type=radio][data-cc="' + cc_data.join(' ') + '"]');
        if (radio.length) {
            radio.prop('checked', true);
            return radio;
        }
        cc_data.pop();
        radio = $('#submit-describe #license-list input[type=radio][data-cc="' + cc_data.join(' ') + '"]');
        radio.prop('checked', true);
        return radio;
    }
    function setWizardFromLicense($license) {
        // Update license wizard if license manually selected.
        $('.noncc.disabled').removeClass('disabled');
        $('input[name^="cc-"]').prop('checked', false);
        $('input[name^="cc-"]:not([data-cc]').prop('checked', true);
        _.each($license.data('cc').split(' '), function(cc) {
            $('input[type=radio][name^="cc-"][data-cc="' + cc + '"]').prop('checked', true);
            setCopyright(cc == 'copyr');
        });
    }
    function updateLicenseBox($license) {
        if ($license.length) {
            var licenseTxt = $license.data('name');
            var url = $license.next('a');
            if (url.length) {
                licenseTxt = format('<a href="{0}">{1}</a>',
                                     url.attr('href'), licenseTxt);
            }
            var $p = $('#persona-license');
            $p.show().find('#cc-license').html(licenseTxt).attr('class', 'license icon ' + $license.data('cc'));
        }
    }
    function licenseChangeHandler() {
        var $license = $('#submit-describe #license-list input[type=radio][name=license-builtin]:checked');
        if ($license.length) {
            setWizardFromLicense($license);
            updateLicenseBox($license);
        } else {
            $('.noncc').addClass('disabled');
        }
    }

    $('#submit-describe input[name="cc-attrib"]').change(function() {
        setCopyright($('input[name="cc-attrib"]:checked').data('cc') == 'copyr');
    });
    $('#submit-describe input[name^="cc-"]').change(function() {
        var $license = setLicenseFromWizard();
        updateLicenseBox($license);
    });
    $('#submit-describe #license-list input[type=radio][name=license-builtin]').change(licenseChangeHandler);

    $('#persona-license .select-license').click(_pd(function() {
        $('#license-list').toggle();
    }));
    licenseChangeHandler();
}

function initSourceSubmitOutcomes() {
    $('#submit-source #id_has_source input').change(function() {
        $('#option_no_source').hide();
        $('#option_yes_source').hide();
        $('#submit-source #id_has_source input').each(function(index, element) {
            var $radio = $(element);
            if ($radio.val() == "yes" && $radio.prop('checked')) {
                $('#option_yes_source').show();
                $('#id_source').attr('required', true);
            }
            if ($radio.val() == "no" && $radio.prop('checked')) {
                $('#option_no_source').show();
                $('#id_source').attr('required', null);

            }
        });
    }).change();
    $('#submit-source').submit(function() {
        // Drop the upload if 'no' is selected.
        $('#submit-source #id_has_source input').each(function(index, element) {
            var $radio = $(element);
            if ($radio.val() == "no" && $radio.prop('checked')) {
                $('#id_source').val('');
            }
        });
    })
}
