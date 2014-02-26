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

    // Fetch all of the app's threads.
    $.get(_userArg(commThreadUrl), function(threads) {
        threads = threads.objects;

        // Show "this version has not been reviewed" for table w/ no results.
        // Gets all version IDs, then adds "No Results" to tables whose
        // data-version is not in the version IDs list.
        var versionIds = _.map(threads, function(thread) {
            return thread.version;
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

        function appendNotesToTable(notes, $table) {
            // Given a list of notes, passes each note into the template
            // and appends to review history table.
            notes = notes.objects;
            for (var i = 0; i < notes.length; i++) {
                var note = notes[i];
                var author = note.author_meta.name;
                var created = moment(note.created).format('MMMM Do YYYY, h:mm:ss a');

                // Append notes to table.
                $table.append(noteTemplate({
                    attachments: note.attachments,
                    body: note.body,
                    // L10n: {0} is author of note, {1} is a datetime. (e.g. "by Kevin on 2014-01-16").
                    metadata: format(gettext('By {0} on {1}'),
                                     [author, created]),
                    noteType: noteTypes[note.note_type],
                }));
            }
        }

        // Fetch all of the notes for each thread.
        for (var i = 0; i < threads.length; i++) {
            var thread = threads[i];
            var $table = $('table.activity[data-version=' + thread.version + ']');
            var commNoteUrl = $itemHistory.data('comm-note-url').replace(threadIdPlaceholder, thread.id);

            $.get(_userArg(commNoteUrl), function(notes) {
                appendNotesToTable(notes, $table);
            });
        }
    });
});
