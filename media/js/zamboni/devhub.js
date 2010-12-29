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
        initSubmit();
        initLicenseFields();
        initCharCount();
        $('.upload-status').bind('upload-success', function(e, json) {
            $("#submit-upload-file-finish").attr("disabled", false);
            $("#id_upload").val(json.upload);
        }).bind('upload-error', function() {
            $("#submit-upload-file-finish").attr("disabled", true);
        });
    }

    // Upload form submit
    if('.upload-status') {
        initUploadControls();
    }

    // Submission > Media
    if($('#submit-media').length) {
        initUploadIcon();
    }
});

function initUploadControls() {
    $('.upload-status').removeClass("hidden");
    $(".invisible-upload").delegate("#upload-file-input", "change", function(e) {
        $('#upload-status-bar').attr('class', '');
        $('#upload-status-text').text("");
        $('#upload-status-results').text("").attr("class", "");
        $('#upload-status-bar div').css('width', 0).show();
        $('#upload-status-bar').removeClass('progress-idle');
        fileUpload($(this), $(this).closest(".invisible-upload").attr('data-upload-url'));
        $('.upload-status').show();
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
        return false;
    });
});


function truncateFields() {
    var els = [
            "#addon_description",
            "#developer_comments"
        ];
    $(els.join(', ')).each(function(i,el) {
        var $el = $(el),
            originalHTML = $el.html();
        $el.delegate("a.truncate_expand", "click", function(e) {
            e.preventDefault();
            $el.html(originalHTML).css('max-height','none');
        })
        .vtruncate({
            truncText: format("&hellip; <a href='#' class='truncate_expand'>{0}</a>",[gettext("More")])
        });
    });
}


function addonFormSubmit() {
    parent_div = $(this);

    (function(parent_div){
        $('form', parent_div.not('#edit-addon-media')).submit(function(e){
            e.preventDefault();
            $.post(parent_div.find('form').attr('action'),
                $(this).serialize(), function(d){
                    parent_div.html(d).each(addonFormSubmit);
                    truncateFields();
                    var e = $(format('<b class="save-badge">{0}</b>',
                                     [gettext('Changes Saved')]))
                              .appendTo(parent_div.find('h3').first());
                    setTimeout(function(){
                        e.css('opacity', 0);
                        setTimeout(function(){ e.remove(); }, 1500);
                    }, 2000);
                });
        });
        z.refreshL10n();
        initCharCount();
    })(parent_div);
}


$("#user-form-template .email-autocomplete")
    .attr("placeholder", gettext("Enter a new author's email address"));

function initEditAddon() {

    $('#edit-addon').delegate('h3 a', 'click', function(e){
        e.preventDefault();

        a = e.target;
        parent_div = $(a).closest('.edit-addon-section');

        (function(parent_div, a){
            parent_div.load($(a).attr('data-editurl'), addonFormSubmit);
        })(parent_div, a);

        return false;
    });

    hideSameSizedIcons();
    initUploadIcon();
}

function initUploadIcon() {
    $('#edit-addon-media').delegate('form', 'submit', multipartUpload);

    $('#edit-addon-media, #submit-media').delegate('#icons_default a', 'click', function(e){
        e.preventDefault();

        $('#edit-icon-error').hide();

        $parent = $(this).closest('li');
        $('input', $parent).attr('checked', true);
        $('#icons_default a.active').removeClass('active');
        $(this).addClass('active');

        $("#id_icon_upload").val("")

        $('#icon_preview_32 img').attr('src', $('img', $parent).attr('src'));
        $('#icon_preview_64 img').attr('src', $('img',
                $parent).attr('src').replace(/32/, '64'));
    });

    $('#edit-addon, #submit-media').delegate('#id_icon_upload', 'change', function(){
        $('#edit-icon-error').hide();
        file = $('#id_icon_upload')[0].files[0];

        if(file.type == 'image/jpeg' || file.type == 'image/png') {
            $('#icons_default input:checked').attr('checked', false);

            $('input[name=icon_type][value='+file.type+']', $('#icons_default'))
                                                          .attr('checked', true)

            $('#icons_default a.active').removeClass('active');
            $('#icon_preview img').attr('src', file.getAsDataURL());
        } else {
            error = gettext('This filetype is not supported.');
            $('#edit-icon-error').text(error).show();
            $('#id_icon_upload').val("");
        }
    });
}

function initVersions() {
    $('#modals').hide();

    $('#modal-delete-version').modal('.version-delete .remove',
        { width: 400,
          callback:function(d){
                $('.version_id', this).val($(d.click_target).attr('data-version'));
                return true;
            }
          });

    $('#modal-cancel').modal('#cancel-review',
        { width: 400
          });


    $('#modal-delete').modal('#delete-addon',
        { width: 400,
          });


    $('#modal-disable').modal('#disable-addon',
        { width: 400,
          callback:function(d){
                $('.version_id', this).val($(d.click_target).attr('data-version'));
                return true;
            }
          });


}

function initSubmit() {
    $('#submit-describe form').delegate('#id_name', 'keyup', slugify)
        .delegate('#id_name', 'blur', slugify)
        .delegate('#edit_slug', 'click', show_slug_edit)
        .delegate('#id_slug', 'change', function() {
            $('#id_slug').attr('data-customized', 1);
            if (!$('#id_slug').val()) {
                $('#id_slug').attr('data-customized', 0);
                slugify;
            }
        });
    $('#id_slug').each(slugify);
}

var file = {},
    xhr = false;

function fileUpload(img, url) {
    var domFile = img[0].files[0];

    file = {};
    file.name = domFile.name || domFile.fileName;
    file.size = domFile.size;
    file.data = '';
    file.aborted = false;

    if(!file.name.match(/\.(xpi|jar|xml)$/i)) {
        error = gettext("The package is not of a recognized type.");
        j = {};
        j.validation = {"errors":1, "messages":[]};
        j.validation.messages.push({"type":"error", "message":error});

        addonUploaded(j, file);
        return false;
    }

    // Remove any form errors from previous POST
    $('ul.errorlist').remove();
    // Prepare the progress bar and status
    text = format(gettext('Preparing {0}'), [file.name]);
    $('#upload-status-text').text(text);

    updateStatus(0);

    // Wrap in a setTimeout so it doesn't freeze the browser before
    // the status above can be set.

    setTimeout( function(){
        uploadFile(domFile, file, url);
    }, 10);

    return true;
}

function abortUpload(e) {
   e.preventDefault();
   file.aborted = true;
   if(xhr) xhr.abort();
}

function textSize(bytes) {
    // Based on code by Cary Dunn (http://bit.ly/d8qbWc).
    var s = ['bytes', 'kb', 'MB', 'GB', 'TB', 'PB'];
    if(bytes == 0) return bytes + " " + s[1];
    var e = Math.floor( Math.log(bytes) / Math.log(1024) );
    return (bytes / Math.pow(1024, Math.floor(e))).toFixed(2)+" "+s[e];
}

function uploadFile(domFile, file, url) {
    xhr = new XMLHttpRequest();
    xhr.upload.addEventListener("progress", function(e) {
        if (e.lengthComputable) {
            var pct = Math.round((e.loaded * 100) / e.total) + "%";
            $('#upload-status-bar div').animate({'width': pct},
                {duration: 500, step:updateStatus });
        }
    }, false);

    var token = $("#upload-file input[name=csrfmiddlewaretoken]").val();

    xhr.open("POST", url, true);

    xhr.onreadystatechange = onupload;
    xhr.setRequestHeader("Content-Type", "application/octet-stream");

    xhr.setRequestHeader("Content-Length", file.size);
    xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');

    xhr.setRequestHeader('Content-Disposition', 'file; name="upload";');
    xhr.setRequestHeader("X-File-Name", file.name);
    xhr.setRequestHeader("X-File-Size", file.size);

    xhr.send(domFile);
}

function updateStatus( percentage ) {
    p = Math.round(percentage);
    size = (p / 100) * file.size;
    // L10n: {0} is the percent of the file that has been uploaded.
    $('#uploadstatus_percent').text(format(gettext('{0}% complete'), [p]));
    // L10n: "{bytes uploaded} of {total filesize}".
    $('#uploadstatus_progress').text(format(gettext('{0} of {1}'),
                                            [textSize(size),
                                             textSize(file.size)]))
                               .attr({'value': size, 'max': file.size});
}


function onupload() {
    if(xhr.readyState == 4) $('#uploadstatus_abort').hide();

    if (xhr.readyState == 4 && xhr.responseText &&
        (xhr.status == 200 || xhr.status == 304)) {
        $('#upload-status-bar div').animate({'width': '100%'},
            {duration: 500,
             step:updateStatus,
             complete: function() {
                text = format(gettext('Validating {0}'), [file.name]);
                $('#upload-status-text').text(text);

                $(this).parent().addClass('progress-idle');

                try {
                    json = JSON.parse(xhr.responseText);
                } catch(err) {
                    // The server isn't returning proper JSON
                    error = gettext("There was an error with your upload.");
                    addonError(error);
                    return false;
                }

                addonUploaded(json);
                }
            });
    } else if(xhr.readyState == 4) {
        // Some sort of error, so display error and prompt them for round 2
        if(file.aborted) {
            addonError(gettext("You aborted the add-on upload."));
        } else {
            addonError(gettext("We were unable to connect to the server."));
        }
    }
}

function addonError(message) {
    $('#upload-status-bar').removeClass('progress-idle')
                           .addClass('bar-fail');
    $('#upload-status-bar div').fadeOut();

    body = "<strong>" + message + "</strong>";

    $('#upload-status-results').html(body).addClass('status-fail');
    $('.upload-status-button-add').hide();
    $('.upload-status-button-close').show();
}

function addonUploaded(json) {
    $('#uploadstatus_abort').hide();

    var v = json.validation;

    if (json.error) {
        $('#upload-status-bar').removeClass('progress-idle')
                               .addClass('bar-fail');
        $('#upload-status-bar div').fadeOut();
        $('#upload-status-text').text(gettext(
            'Unexpected server error while validating.'));
        return;
    }

    if(!v) {
        setTimeout(function(){
            $.getJSON(json.url, addonUploaded);
        }, 1000);
    } else {
        $('#upload-status-bar').removeClass('progress-idle')
                               .addClass('bar-' +
                                         (v.errors ? 'fail' : 'success'));
        $('#upload-status-bar div').fadeOut();

        text = format(gettext('Validated {0}'), [file.name]);
        $('#upload-status-text').text(text);

        var body = "<strong>";
        if(!v.errors) {
            body += format(ngettext(
                    "Your add-on passed validation with 0 errors and {0} warning.",
                    "Your add-on passed validation with 0 errors and {0} warnings.",
                    v.warnings), [v.warnings]);
        } else {
            body += format(ngettext(
                    "Your add-on failed validation with {0} error.",
                    "Your add-on failed validation with {0} errors.",
                    v.errors), [v.errors]);
        }
        body += "</strong>";

        var numErrors = 0,
            max = 5,
            overflowed = false;
        body += "<ul>";
        if(v.errors) {
            $.each(v.messages, function(k, t) {
                if(t.type == "error") {
                    numErrors++;
                    if (numErrors <= max) {
                        body += '<li>' + t.message + '</li>';
                    } else {
                        overflowed = true;
                    }
                }
            });
            if (overflowed) {
                // L10n: first argument is the number of errors.
                body += '<li>' + format(gettext('...and {0} more'),
                                        [numErrors-max]) + '</li>';
            }
        }
        body += "</ul>";

        if (json.full_report_url) {
            // There might not be a link to the full report
            // if we get an early error like unsupported type.
            body += format('<a href="{0}" target="_blank">{1}</a>',
                           [json.full_report_url,
                            gettext('See full validation report')]);
        }

        if (json.validation.detected_type == 'search') {
            $("#create-addon .platform").hide();
        } else {
            $("#create-addon .platform:hidden").show();
        }

        statusclass = v.errors ? 'status-fail' : 'status-pass';
        $('#upload-status-results').html(body).addClass(statusclass);
        resetFileInput();

        if(!v.errors) {
            $(".upload-status").trigger("upload-success", [json]);
        } else {
            $(".upload-status").trigger("upload-error", [json]);
        }
    }

}


function resetFileInput() {
    upload = $("<input type='file'>").attr('name', 'upload')
                                     .attr('id', 'upload-file-input');
    $('#upload-file-input').replaceWith(upload); // Clear file input
}


function initEditVersions() {
    // Modal box
    $modal = $(".add-file-modal").modal(".add-file", {
        width: '450px',
        hideme: false,
        callback: resetModal
    });

    // Cancel link
    $('.upload-file-cancel').click(function(e) {
        e.preventDefault();
        $modal.hideMe();
    });

    // Abort upload
    $('#uploadstatus_abort a').click(abortUpload);

    // Handle uploader events
    $('.upload-status').bind('upload-success', function(e,json) {
        $("#upload-file-finish").attr("disabled", false);
        $("#id_upload").val(json.upload);
    }).bind('upload-error', function() {
        $modal.setPos(); // Reposition since the error report has been added.
        $("#upload-file-finish").attr("disabled", true);
    });

    $("#upload-file-finish").click(function (e) {
        e.preventDefault();
        $tgt = $(this);
        if ($tgt.attr("disabled")) return;
        $.post($("#upload-file").attr("action"), $("#upload-file").serialize(), function (resp) {
            $("#file-list tbody").append(resp);
            var new_total = $("#file-list tr").length;
            $("#id_files-TOTAL_FORMS").val(new_total);
            $("#id_files-INITIAL_FORMS").val(new_total);
            $modal.hideMe();
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

    function resetModal(fileInput) {
        if (fileInput === undefined) fileInput = true;

        file = {name: '', size: 0, data: '', aborted: false};

        $('.upload-file-box').show();
        $('.upload-status').hide();

        $('.upload-status-button-add').show();
        $('.upload-status-button-close').hide();

        $('#upload-status-bar').attr('class', '');
        $('#upload-status-text').text("");
        if (fileInput) resetFileInput(); // Clear file input
        $('#upload-status-results').text("").attr("class", "");
        $('#upload-status-bar div').css('width', 0).show();
        $('#upload-status-bar').removeClass('progress-idle');
        $("#upload-file-finish").attr("disabled", true);


        updateStatus(0);
        $('#uploadstatus_abort').show();

        return true;
    }
}

function initPayments() {
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
        $("<a class='extra' target='_blank' href='http://www.mozilla.org/foundation/donate.html'>"+gettext('Learn more')+"</a>"));
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

function multipartUpload(e) {
    e.preventDefault();

    var xhr = new XMLHttpRequest(),
        boundary = "BoUnDaRyStRiNg";

    xhr.open("POST", $(this).attr('action'), true)
    xhr.overrideMimeType('text/plain; charset=x-user-defined-binary');
    xhr.setRequestHeader('Content-length', false);
    xhr.setRequestHeader("Content-Type", "multipart/form-data;" +
                                         "boundary=" + boundary);

    // Sorry this is so ugly.
    content = [
        "Content-Type: multipart/form-data; boundary=" + boundary,
        "",
        "--" + boundary,
        "Content-Disposition: form-data; name=\"icon_type\"",
        "",
        $('input[name="icon_type"]:checked', $('#icons_default')).val(),

        "--" + boundary,
        "Content-Disposition: form-data; name=\"csrfmiddlewaretoken\"",
        "",
        $('input[name="csrfmiddlewaretoken"]', $('#edit-addon-media')).val()];

    if($('input[name=icon_type]:checked').val().match(/^image\//)) {
        // There's a file to be uploaded.

        var file = $('#id_icon_upload')[0].files[0],
            data = file.getAsBinary();

        image = [
            "--" + boundary,
            "Content-Disposition: form-data; name=\"icon_upload\";" +
            "filename=\"new-icon\"",
            "Content-Type: " + file.type,
            "",
            data,
            "--" + boundary + "--"];

        content = $.merge(content, image);
    }

    xhr.onreadystatechange = function() {
        if (xhr.readyState == 4 && xhr.responseText &&
            (xhr.status == 200 || xhr.status == 304)) {
            $('#edit-addon-media').html(xhr.responseText);

            hideSameSizedIcons();
        }
    };

    xhr.sendAsBinary(content.join('\r\n'));
}

function hideSameSizedIcons() {
    icon_sizes = [];
    $('#icon_preview_readonly img').show().each(function(){
        size = $(this).width() + 'x' + $(this).height();
        if($.inArray(size, icon_sizes) >= 0) {
            $(this).hide();
        }
        icon_sizes.push(size)
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
                    ctxDiv, lines, code, innerCode;
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
                if (msg.context) {
                    ctxDiv = $(format(
                        '<div class="context">' +
                            '<div class="file">{0}:</div></div>',
                                                        [msg.file]));
                    code = $('<div class="code"></div>');
                    lines = $('<div class="lines"></div>');
                    code.append(lines);
                    innerCode = $('<div class="inner-code"></div>');
                    code.append(innerCode);
                    $.each(msg.context, function(n, c) {
                        lines.append(
                            $(format('<div>{0}</div>', [msg.line + n])));
                        innerCode.append($(format('<div>{0}</div>', [c])));
                    });
                    ctxDiv.append(code);
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
            else if (msg['type'] == 'warning') {
                msgMap[msg.tier].warnings += 1;
            }
        });
        return msgMap;
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

    $('.addon-validator-suite').live('validate', function(e) {
        var el = $(this),
            url = el.attr('data-validateurl');

        prepareToGetResults(el);

        $.ajax({type: 'POST',
                url: url,
                data: {},
                success: function(data) {
                    if (data.validation == '') {
                        // Note: traceback is in data.task_error
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

    // Setup revalidate link.
    $('#addon-validator-suite .suite-summary a').click(function(e) {
        $('#addon-validator-suite').trigger('validate');
        e.preventDefault();
    });

});
