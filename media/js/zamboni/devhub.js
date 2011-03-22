$(document).ready(function() {

    // Edit Add-on
    if($("#edit-addon").length){
        initEditAddon();
    }

    //Ownership
    if ($("#author_list").length) {
        initAuthorFields();
        initLicenseFields();
    }

    //Payments
    if ($('.payments').length) {
        initPayments();
    }

    // Edit Versions
    if($('.edit-version').length) {
        initEditVersions();
    }

    // View versions
    if($('#version-list').length) {
        initVersions();
    }

    // Submission process
    if($('.addon-submission-process').length) {
        initLicenseFields();
        initCharCount();
        initSubmit();
    }

    // Validate addon (standalone)
    if($('.validate-addon').length) {
        initSubmit();
    }

    // Submission > Describe
    if ($("#submit-describe").length) {
        initCatFields();
    }

    // Submission > Media
    if($('#submit-media').length) {
        initUploadIcon();
        initUploadPreview();
    }

    // Add-on uploader
    if($('#upload-addon').length) {
        $('#upload-addon').addonUploader();
    }

    if ($(".version-upload").length) {
        $modal = $(".add-file-modal").modal(".version-upload", {
            width: '450px',
            hideme: false
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
                    $modal.setPos();
                }
            });
        }));
        if (window.location.hash === '#version-upload') {
            $modal.render();
        }
    }

    $(".invisible-upload a").click(_pd(function() {}));

    // Choosing platform when submitting an Addon and/or files.
    if ($('input.platform').length) {
        initPlatformChooser();
    }

    // when to start and stop image polling
    if ($('#edit-addon-media').length) {
        imageStatus.start();
    }
    $('#edit-addon-media').bind('click', function() {
        imageStatus.cancel();
    })
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
        var form = $(this).parents('form');
        if ($(this).val() == '1') {
            // Platform=ALL
            if ($(this).attr('checked')) {
                // Uncheck all other platforms:
                $('input.platform:not([value="1"])', form).attr('checked',
                                                                 false);
            }
        } else {
            if ($(this).attr('checked')) {
                // Any other platform was checked so uncheck Platform=ALL
                $('input.platform[value="1"]', form).attr('checked', false);
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
    //         "#addon_description",
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
        }
        $('.edit-media-button button').attr('disabled', false);
        $('form', parent_div).submit(function(e){
            e.preventDefault();
            var old_baseurl = baseurl();
            parent_div.find(".item").removeClass("loaded").addClass("loading");
            var scrollBottom = $(document).height() - $(document).scrollTop();

            $.post(parent_div.find('form').attr('action'),
                $(this).serialize(), function(d) {
                    parent_div.html(d).each(addonFormSubmit);
                    if (!parent_div.find(".errorlist").length && old_baseurl && old_baseurl !== baseurl()) {
                        document.location = baseurl();
                    }
                    $(document).scrollTop($(document).height() - scrollBottom);
                    truncateFields();
                    annotateLocalizedErrors(parent_div);
                    if(parent_div.is('#edit-addon-media')) {
                        imageStatus.start();
                        hideSameSizedIcons();
                    }

                    if (!parent_div.find(".errorlist").length) {
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

        a = e.target;
        parent_div = $(a).closest('.edit-addon-section');

        (function(parent_div, a){
            parent_div.find(".item").addClass("loading");
            parent_div.load($(a).attr('data-editurl'), function(){
                if($('#addon_categories_edit').length) {
                    initCatFields();
                }
                $(this).each(addonFormSubmit);
            });
        })(parent_div, a);

        return false;
    });

    // Init icon javascript.
    hideSameSizedIcons();
    initUploadIcon();
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
    $(last).after(last_clone);
    $('#id_files-TOTAL_FORMS').val(parseInt(forms_count) + 1);

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

        $(form).find('.preview-thumb').addClass('loading')
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
        form.find('[name$=upload_hash]').val(upload_hash);
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

    $f.delegate('#screenshot_upload', "upload_finished", upload_finished)
      .delegate('#screenshot_upload', "upload_success", upload_success)
      .delegate('#screenshot_upload', "upload_start", upload_start)
      .delegate('#screenshot_upload', "upload_errors", upload_errors)
      .delegate('#screenshot_upload', "upload_start_all", upload_start_all)
      .delegate('#screenshot_upload', "upload_finished_all", upload_finished_all)
      .delegate('#screenshot_upload', 'change', function(e){
        $(this).imageUploader();
      });

    $("#edit-addon-media, #submit-media").delegate("#file-list .remove", "click", function(e){
        e.preventDefault();
        var row = $(this).closest(".preview");
        row.find(".delete input").attr("checked", "checked");
        row.slideUp(300, renumberPreviews);
    });
}

function initUploadIcon() {
    $('#edit-addon-media, #submit-media').delegate('#icons_default a', 'click', function(e){
        e.preventDefault();

        var $error_list = $('#icon_preview').parent().find(".errorlist"),
            $parent = $(this).closest('li');

        $('input', $parent).attr('checked', true);
        $('#icons_default a.active').removeClass('active');
        $(this).addClass('active');

        $("#id_icon_upload").val("");

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
            $('input[name=icon_type][value='+file.type+']', $('#icons_default'))
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
      .delegate('#id_icon_upload', 'change', function(e){
        $(this).imageUploader();
      });
}

function fixPasswordField($context) {
    // This is a hack to prevent password managers from automatically
    // deleting add-ons.  See bug 630126.
    $context.find('input[type=password]').each(function(){
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

    $('#modal-cancel').modal('#cancel-review', {width: 400});
    $('#modal-delete').modal('#delete-addon', {width: 400,
                                callback: function(obj) {
                                    return fixPasswordField(this);
                                }});
    $('#modal-disable').modal('#disable-addon',
        {width: 400,
         callback: function(d){
               $('.version_id', this).val($(d.click_target).attr('data-version'));
                return true;
         }});

}

function initSubmit() {
    var dl = $('body').attr('data-default-locale');
    var el = format('#trans-name [lang={0}]', dl);
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
        hideme: false
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
}

function initPayments() {
    if (z.noEdit) return;
    var previews = [
        "img/zamboni/contributions/passive.png",
        "img/zamboni/contributions/after.png",
        "img/zamboni/contributions/roadblock.png",
    ],
        media_url = $("body").attr("data-media-url"),
        to = false,
        img = $("<img id='contribution-preview'/>");
        moz = $("input[value=moz]");
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
    $("#do-setup").click(function (e) {
        e.preventDefault();
        $("#setup").removeClass("hidden").show();
        $(".intro").hide();
    });
    $("#setup-cancel").click(function (e) {
        e.preventDefault();
        $(".intro").show();
        $("#setup").hide();
    });
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
}

function initCatFields() {
    $(".select-addon-cats").each(function() {
        var $parent = $(this).closest("[data-max-categories]"),
            $main = $(this).find(".addon-categories"),
            $misc = $(this).find(".addon-misc-category"),
            maxCats = parseInt($parent.attr("data-max-categories"));
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
        $("input", $main).live("change", checkMain);
        $("input", $misc).live("change", checkOther);
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
            timeout = setTimeout(function () {
                tgt.addClass("ui-autocomplete-loading")
                   .removeClass("invalid")
                   .removeClass("valid");
                request = $.ajax({
                    url: tgt.attr("data-src"),
                    data: {q: tgt.val()},
                    success: function(data) {
                        tgt.removeClass("ui-autocomplete-loading")
                           .addClass("valid");
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
    $('p.add-app a').live('click', function(e) {
        e.preventDefault();
        var outer = $(this).closest('form');

        $('tr.app-extra', outer).each(function() {
            addAppRow(this);
        });

        $('.new-apps', outer).toggle();

        $('.new-apps ul').delegate('a', 'click', function(e) {
            e.preventDefault();
            var extraAppRow = $('tr.app-extra td[class=' + $(this).attr('class') + ']', outer);
            extraAppRow.parents('tr.app-extra').find('input:checkbox').removeAttr('checked')
                       .closest('tr').removeClass('app-extra');

            $(this).closest('li').remove();

            if (!$('tr.app-extra', outer).length)
                $('p.add-app', outer).hide();
        });
    });

    $('.compat-versions .remove').live('click', function(e) {
        e.preventDefault();
        var appRow = $(this).closest('tr');

        appRow.addClass('app-extra');

        if (!appRow.hasClass('app-extra-orig'))
            appRow.find('input:checkbox').attr('checked', true);

        $('p.add-app:hidden', $(this).closest('form')).show();
        addAppRow(appRow);
    });

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
                var img = Image();
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

    $('input[type=file]', form).each(function(){
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
    if (!$('.new-apps ul', outer).length)
        $('.new-apps', outer).html('<ul></ul>');
    if ($('.new-apps ul a[class=' + appClass + ']', outer).length)
        return;
    var appLabel = $('td.app', obj).text(),
        appHTML = '<li><a href="#" class="' + appClass + '">' + appLabel + '</a></li>';
    $('.new-apps ul', outer).append(appHTML);
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


$(document).ready(function() {

    function buildResults(suite, data) {
        var validation = data.validation,
            msgMap = buildMsgMap(validation.messages),
            summaryTxt;

        if (validation.errors > 0) {
            summaryTxt = gettext('Add-on failed validation.');
        } else {
            summaryTxt = gettext('Add-on passed validation.');
        }
        $('.suite-summary span', suite).text(summaryTxt);
        $('.result-summary', suite).text('').css('visibility', 'visible');
        $('.suite-summary', suite).show();

        for (var tierNum in msgMap) {
            var tierData = msgMap[tierNum],
                tier = $('[class~="test-tier"]' +
                         '[data-tier="' + tierNum + '"]', suite),
                resContainer = $('#suite-results-tier-' + tierNum),
                results = $('.tier-results', resContainer),
                errorsTxt, warningsTxt, summaryMsg;

            results.empty();
            // e.g. '1 error, 3 warnings'
            summaryMsg = format(ngettext('{0} error', '{0} errors',
                                         tierData.errors),
                                         [tierData.errors]) + ', ' +
                         format(ngettext('{0} warning', '{0} warnings',
                                         tierData.warnings),
                                         [tierData.warnings]);
            $('.tier-summary', tier).text(summaryMsg);
            $('.result-summary', resContainer).text(summaryMsg);

            tier.removeClass('ajax-loading');
            results.removeClass('ajax-loading');
            if (tierData.errors > 0) {
                tier.addClass('tests-failed');
                results.addClass('tests-failed');
            } else if (tierData.warnings > 0) {
                tier.addClass('tests-passed');
                results.addClass('tests-passed-warnings');
            } else if (validation.ending_tier
                       && validation.ending_tier < tierNum) {
                tier.addClass('tests-notrun');
                results.addClass('tests-notrun');
                $('.tier-summary', tier).text(gettext('Tests not run'));
                results.append('<span>' +
                               gettext('These tests were not run.') +
                               '</span>');
                $('.result-summary', resContainer).html('&nbsp;');
            } else {
                tier.addClass('tests-passed');
                results.addClass('tests-passed');
                results.append('<span>' +
                               gettext('All tests passed successfully.') +
                               '</span>');
                // There might still be some messages below
                // but we don't care about showing them.
                continue;
            }

            $.each(tierData.messages, function(i, msg) {
                var msgDiv = $('<div class="msg"><h5></h5></div>'),
                    prefix = msg['type']=='warning' ? gettext('Warning')
                                                    : gettext('Error'),
                    ctxDiv, lines, code, innerCode, ctxFile;
                msgDiv.attr('id', msgId(msg.uid));
                msgDiv.addClass('msg-' + msg['type']);
                $('h5', msgDiv).html(msg.message);
                if (typeof(msg.description) === 'undefined'
                    || msg.description === '') {
                    msg.description = [];
                } else if (typeof(msg.description) === 'string') {
                    // TODO(kumar) ask Matt to make the JSON format
                    // more consistent.
                    // Currently it can be either of these:
                    //      descripion: "foo"
                    //      description: ["foo", "bar"]
                    msg.description = [msg.description];
                }
                $.each(msg.description, function(i, val) {
                    msgDiv.append(format('<p>{0}: {1}</p>', [prefix, val]));
                });
                if (msg.description.length == 0) {
                    msgDiv.append('<p>&nbsp;</p>');
                }
                ctxFile = msg.file;
                if (ctxFile) {
                    if (typeof(ctxFile) === 'string') {
                        ctxFile = [ctxFile];
                    }
                    // e.g. ["silvermelxt_1.3.5.xpi",
                    //       "chrome/silvermelxt.jar"]
                    ctxFile = joinPaths(ctxFile);
                    ctxDiv = $(format(
                        '<div class="context">' +
                            '<div class="file">{0}</div></div>',
                                                        [ctxFile]));
                    if (msg.context) {
                        code = $('<div class="code"></div>');
                        lines = $('<div class="lines"></div>');
                        code.append(lines);
                        innerCode = $('<div class="inner-code"></div>');
                        code.append(innerCode);
                        msg.context = formatCodeIndentation(msg.context);
                        $.each(msg.context, function(n, c) {
                            lines.append(
                                $(format('<div>{0}</div>', [msg.line + n])));
                            innerCode.append(
                                $(format('<div>{0}</div>', [c])));
                        });
                        ctxDiv.append(code);
                    }
                    msgDiv.append(ctxDiv);
                }
                results.append(msgDiv);
            });
        }
    }

    function buildMsgMap(messages) {
        // The tiers will not apper in the JSON
        // if there are no errors.  FIXME?
        var msgMap = {
            1: {errors: 0, warnings: 0, messages: []},
            2: {errors: 0, warnings: 0, messages: []},
            3: {errors: 0, warnings: 0, messages: []},
            4: {errors: 0, warnings: 0, messages: []}
        };
        $.each(messages, function(i, msg) {
            msgMap[msg.tier].messages.push(msg);
            if (msg['type'] == 'error') {
                msgMap[msg.tier].errors += 1;
            }
            else if (msg['type'] == 'warning' || msg['type'] == 'notice') {
                msgMap[msg.tier].warnings += 1;
            }
        });
        return msgMap;
    }

    function joinPaths(parts) {
        var p = '';
        $.each(parts, function(i, part) {
            if (!part || typeof(part) !== 'string') {
                // Might be null or empty string.
                return;
            }
            if (p.length) {
                p += '/';
                if (part.substring(0,1) === '/') {
                    // Prevent double slashes.
                    part = part.substring(1);
                }
            }
            p += part;
        });
        return p;
    }

    function msgId(hash) {
        return 'v-msg-' + hash;
    }

    function prepareToGetResults(el) {
        $('.test-tier, .tier-results', el).removeClass('tests-failed',
                                                       'tests-passed');
        $('.test-tier, .tier-results', el).addClass('ajax-loading');
        $('.tier-results', el).empty();
        $('.tier-results', el).append('<span>' +
                                      gettext('Running tests...') +
                                      '</span>');
        $('.result-summary', el).text('.').css('visibility', 'hidden');
        $('.test-tier .tier-summary', el).text(gettext('Running tests...'));
        $('.suite-summary', el).hide();
    }

    // Displays a global error on all tiers.
    // NOTE: this can probably be simplified if the JSON format is updated.
    function messagesForAllTiers(header, description) {
        return [
            {'type':'error', message: header,
             description: [description], tier: 1, uuid: '1'},
            {'type':'error', message: header,
             description: [description], tier: 2, uuid: '2'},
            {'type':'error', message: header,
             description: [description], tier: 3, uuid: '3'},
            {'type':'error', message: header,
             description: [description], tier: 4, uuid: '4'}
        ]
    }

    function formatCodeIndentation(lines) {
        var indent = null;
        $.each(lines, function(i, code) {
            if (code === null) {
                code = ''; // blank line
            }
            lines[i] = code;
            var m = code.length - code.replace(/^\s+/, '').length;
            if (indent === null) {
                indent = m;
            }
            // Look for the smallest common indent of white space.
            if (m < indent) {
                indent = m;
            }
        });
        $.each(lines, function(i, code) {
            if (indent > 0) {
                // Dedent all code to common level.
                code = code.substring(indent);
                lines[i] = code;
            }
            var n = code.search(/[^\s]/); // first non-space char
            if (n > 0) {
                lines[i] = '';
                // Add back the original indentation.
                for (var x=0; x<n; x++) {
                    lines[i] += '&nbsp;';
                }
                lines[i] += $.trim(code);
            }
        });
        return lines;
    }

    $('.addon-validator-suite').live('validate', function(e) {
        var el = $(this),
            url = el.attr('data-validateurl');

        prepareToGetResults(el);

        $.ajax({type: 'POST',
                url: url,
                data: {},
                success: function(data) {
                    if (data.validation == '') {
                        // Note: traceback is in data.error
                        data.validation = {};
                        data.validation.messages = messagesForAllTiers(
                            gettext('Error'),
                            gettext('Validation task could not complete ' +
                                    'or completed with errors'));
                    }
                    buildResults(el, data);
                },
                error: function(XMLHttpRequest, textStatus, errorThrown) {
                    $('.test-tier, .tier-results', el).removeClass(
                                                            'ajax-loading');
                    $('.test-tier, .tier-results', el).addClass(
                                                            'tests-failed');
                    buildResults(el, {
                        validation: {
                            messages: messagesForAllTiers(
                                            gettext('Error'),
                                            gettext('Internal server error'))
                        }
                    });
                },
                dataType: 'json'
        });
    });

    // Validate when the page loads.
    $('#addon-validator-suite').trigger('validate');

});
