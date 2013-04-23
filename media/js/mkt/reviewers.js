(function() {
    if (z.capabilities.mobile) {
        z.body.addClass('mobile');
    }
    if (z.capabilities.tablet) {
        z.body.addClass('tablet');
    }
    if (z.capabilities.desktop) {
        z.body.addClass('desktop');
    }

    initPrefetchManifest();

     // Reviewer tool search.
    initAdvancedMobileSearch();
    initMobileMenus();
    initClearSearch();

    if ($('.theme-search').length) {
        initSearch(true);
    } else {
        initSearch();
    }
})();


function initClearSearch() {
    var $clear = $('.clear-queue-search'),
        $appQueue = $('.search-toggle'),
        $search = $('.queue-search'),
        $searchIsland = $('#search-island');

    $clear.click(_pd(function() {
        $appQueue.show();
        $('#id_q').val('');
        $clear.hide();
        $searchIsland.hide();
    }));
}


function initSearch(isTheme) {
    var search_results = getTemplate($('#queue-search-template'));
    var no_results = getTemplate($('#queue-search-empty-template'));

    var $clear = $('.clear-queue-search'),
        $appQueue = $('.search-toggle'),
        $search = $('.queue-search'),
        $searchIsland = $('#search-island');

    if ($search.length) {
        // An underscore template for more advanced rendering.
        var search_result_row = _.template($('#queue-search-row-template').html());

        var apiUrl = $search.data('api-url');
        var review_url = $search.data('review-url');
        var statuses = $searchIsland.data('statuses');

        $search.on('submit', 'form', _pd(function() {
            var $form = $(this);
            $.get(apiUrl, $form.serialize()).done(function(data) {
                // Hide app queue.
                $appQueue.hide();
                $clear.show();
                // Show results.
                if (data.meta.total_count === 0) {
                    $searchIsland.html(no_results({})).show();
                } else {
                    var results = [];
                    $.each(data.objects, function(i, item) {
                        if (isTheme) {
                            item = buildThemeResultRow(item, review_url,
                                                       statuses);
                        } else {
                            item = buildAppResultRow(item, review_url,
                                                     statuses);
                        }
                        results.push(search_result_row(item));
                    });
                    $searchIsland.html(
                        search_results({rows: results.join('')})).show();
                }
            });
        }));
    }
}


function buildAppResultRow(app, review_url, statuses) {
    var flags = [];
    app.review_url = review_url.replace('__slug__', app.slug);
    app.status = statuses[app.status];
    if (app.latest_version_status) {
        app.status += format(' | {0}', statuses[app.latest_version_status]);
    }
    if (app.is_packaged) {
        flags.push({suffix: 'packaged-app', title: gettext('Packaged App')});
    }
    if (app.current_version.has_info_request) {
        flags.push({suffix: 'reviewer-info', title: gettext('More Information Requested')});
    }
    if (app.current_version.has_editor_comment) {
        flags.push({suffix: 'editor', title: gettext('Contains Editor Comment')});
    }
    // TODO: This key doesn't exist on the app object...being developed.
    // Markup and CSS are ready. Change this if sample key below is wrong.
    if (app.current_version.escalated) {
        flags.push({suffix: 'escalated', title: gettext('Escalated')});
    }
    app.flags = flags;

    if (app.price === null) {
        app.price = gettext('Free');
    }

    return app;
}


function buildThemeResultRow(theme, review_url, statuses) {
    // Add some extra pretty attrs for the template.
    theme.name = theme.name[0];

    // Rather resolve URLs in backend, infer from slug.
    theme.review_url = review_url.replace(
        '__slug__', theme.slug);
    theme.status = statuses[theme.status];
    return theme;
}


function initMobileMenus() {
    // Nav action menu overlays for queues and logs.
    var $logTabOverlay = $('#log-tab-overlay');
    var $queueTabOverlay = $('#queue-tab-overlay');
    $('.trigger-queues').click(_pd(function() {
        if (z.capabilities.mobile || z.capabilities.tablet) {
            $queueTabOverlay.show();
        }
    }));
   $('.trigger-logs').click(_pd(function() {
        if (z.capabilities.mobile || z.capabilities.tablet) {
            $logTabOverlay.show();
        }
    }));
    $('.nav-action-menu button').click(_pd(function() {
        // Turn buttons into links on nav tab overlays.
        var $button = $(this);
        if ($button.data('url') == '#cancel') {
            $queueTabOverlay.hide();
            $logTabOverlay.hide();
        } else {
            window.location.href = $button.data('url');
        }
    }));
}


function initAdvancedMobileSearch() {
    // Value selectors for mobile advanced search.
    $('.value-select-field').click(function() {
        $(this).next('div[role="dialog"]').show();
    });
    $('div[role="dialog"] .cancel').click(_pd(function() {
        $(this).closest('div[role="dialog"]').hide();
    }));

    var $advSearch = $('.advanced-search.desktop');
    $('.advanced-search li[role="option"] input').change(
        syncPrettyMobileForm).each(function(i, input) {
            /* Since Gaia form doesn't use selects, browser does not populate
               our Gaia form after submitting with GET params. We sync data
               between the populated hidden desktop advanced search form to our
               mobile Gaia form. */
            var $input = $(input);
            var val = $input.attr('value');
            if (val) {
                /* If input checked/selected in the desktop form, check/select
                   it in our Gaia form. */
                var nameSelect = '[name="' + $input.attr('name') + '"]';
                var $inputs = $(nameSelect + ' option[value="' + val + '"]:selected',
                                $advSearch);
                $inputs = $inputs.add(
                    $('input[value="' + val + '"]:checked' + nameSelect,
                      $advSearch));
                if ($inputs.length) {
                    $input.prop('checked', true);
                }
            }
        });
    syncPrettyMobileForm();
}


function syncPrettyMobileForm() {
    /* The pretty mobile visible form does not contain actual form elements.
       Value selector form elements are hidden and contained within overlays.
       When we check a value our form in the overlay, we sync the pretty
       representation of the form. */

    // Value selector is the name of the Gaia mobile radio/checkbox form.
    var $valSelectFields = $('.value-select-field');

    $valSelectFields.each(function(index, valSelectField) {
        var $valSelectField = $(valSelectField);
        var name = $valSelectField.data('field');

        var valStrs = [];
        var $checkedInputs = $('li[role="option"] input[name="' + name + '"]:checked');
        $checkedInputs.each(function(index, input) {
            // Build pretty string.
            valStrs.push($(input).next('span').text().trim());
        });

        // Sync new selected value to our span in the pretty form.
        var firstPrettyVal = $('li[role="option"]:first-child span',
            $valSelectField.next('div[role="dialog"]')).text();
        $('.' + name + '.selected-val span').text(
            valStrs.length ? valStrs.join() :
            $('.multi-val', $valSelectField).length ? gettext('Any') :
                                                      firstPrettyVal);
    });
}


function initPrefetchManifest() {
   var $viewManifest = $('#view-manifest'),
       $manifest = $('#manifest-contents');

    if (!$viewManifest.length) {
        return;
    }

    // Prefetch manifest.
    $.getJSON($viewManifest.data('url'), function(data) {
        var manifestContents = data;

        // Show manifest.
        $viewManifest.click(_pd(function() {
            var $this = $viewManifest,
                $manifest = $('#manifest-headers, #manifest-contents');
            if ($manifest.length) {
                $manifest.toggle();
            } else {
                if (!manifestContents.success) {
                    // If requests couldn't fetch the manifest, let Firefox render it.
                    $('<iframe>', {'id': 'manifest-contents',
                                   'src': 'view-source:' + $this.data('manifest')}).insertAfter($this);
                } else {
                    var contents = '',
                        headers = '';

                    _.each(manifestContents.content.split('\n'), function(v, k) {
                        if (v) {
                            contents += format('<li>{0}</li>', v);
                        }
                    });
                    $('<ol>', {'id': 'manifest-contents',
                               'html': contents}).insertAfter($this);

                    if (manifestContents.headers) {
                        _.each(manifestContents.headers, function(v, k) {
                            headers += format('<li><b>{0}:</b> {1}</li>', k, v);
                        });
                        $('<ol>', {'id': 'manifest-headers',
                                   'html': headers}).insertAfter($this);
                    }

                    if (manifestContents.permissions) {
                        var permissions = format(
                            '<h4>{0}</h4><dl>', gettext('Requested Permissions:'));
                        permissions += _.map(
                            manifestContents.permissions,
                            function(details, permission) {
                                var type;
                                if (details.type) {
                                    switch (details.type) {
                                        case 'cert':
                                            type = gettext('Certified');
                                            break;
                                        case 'priv':
                                            type = gettext('Privileged');
                                            break;
                                        case 'web':
                                            type = gettext('Unprivileged');
                                    }
                                }
                                return format(
                                    '<dt>{0}</dt><dd>{1}, {2}</dd>',
                                    permission, type,
                                    details.description || gettext('No reason given'));
                            }
                        ).join('');
                        $('<div>', {'id': 'manifest-permissions',
                                    'html': permissions}).insertAfter($this);
                    }
                }
            }
        }));
    });
}
