define('reviewersCommbadge', [], function() {
    var $itemHistory = $('#review-files');
    var commThreadUrl = $itemHistory.data('comm-thread-url');
    var threadIdPlaceholder = $itemHistory.data('thread-id-placeholder');
    var noteTypes = $itemHistory.data('note-types');

    var noteTemplate = _.template($('#commbadge-note').html());
    var noResults = $('#no-notes').html();

    function _userArg(url) {
        // Persona user token.
        return urlparams(url, {'_user': localStorage.getItem('0::user')});
    }

    // Get all of the app's threads.
    $.get(_userArg(commThreadUrl), function(data) {
        $threads = $(data.objects);

        // Show "this version has not been reviewed" for table w/ no results.
        var versionIds = [];
        $threads.each(function(i, thread) {
            // A roundabout way of finding which tables have no threads, but it
            // don't have many choices since it depends on the API call.
            versionIds.push(thread.version);
        });
        $('table.activity').each(function(i, table) {
            var $table = $(table);
            if (versionIds.indexOf($table.data('version')) === -1) {
                if ($table.find('tbody').length) {
                   $table = $table.find('tbody');
                }
                $table.append(noResults);
            }
        });

        $threads.each(function(i, thread) {
            var $table = $('table.activity[data-version=' + thread.version + ']');
            var commNoteUrl = $itemHistory.data('comm-note-url').replace(threadIdPlaceholder, thread.id);

            // Get all of the thread's notes.
            $.get(_userArg(commNoteUrl), function(data) {
                $(data.objects).each(function(i, note) {
                    var author = note.author_meta.name;
                    var created = moment(note.created).format('MMMM Do YYYY, h:mm:ss a');

                    // Append notes to table.
                    $table.append(noteTemplate({
                        attachments: note.attachments,
                        body: note.body,
                        metadata: format(gettext('By {0} on {1}'),
                                         [author, created]),
                        noteType: noteTypes[note.note_type],
                     }));
                 });
            });
        });
    });
});
