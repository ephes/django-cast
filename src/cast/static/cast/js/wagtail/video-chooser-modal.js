VIDEO_CHOOSER_MODAL_ONLOAD_HANDLERS = {
    'chooser': function(modal, jsonData) {
        if (modal.castMediaChooserCleanup) modal.castMediaChooserCleanup();
        var body = $(modal.body);
        var searchForm = $('form.media-search', body);
        var searchUrl = searchForm.attr('action');
        var uploadForm = $('form.media-upload', body);
        var submitButtons = uploadForm.find(':submit');
        var closeTarget = $(modal.dialog || modal.container);
        var currentTag;
        var searchTimer;
        var resultsRequest;
        var uploadAttempt;
        var generation = 0;
        var retired = false;

        function newIntent() {
            clearTimeout(searchTimer);
            generation += 1;
            if (resultsRequest) {
                var request = resultsRequest;
                resultsRequest = null;
                request.abort();
            }
            return generation;
        }

        function retire() {
            if (retired) return;
            retired = true;
            newIntent();
            if (uploadAttempt) {
                var attempt = uploadAttempt;
                uploadAttempt = null;
                attempt.request.abort();
            }
            body.find('*').addBack().off('.castMediaChooser');
            closeTarget.off('.castMediaChooser');
            observer.disconnect();
            if (modal.castMediaChooserCleanup === retire) delete modal.castMediaChooserCleanup;
        }

        function isCurrent() {
            if (!retired && (!body[0].isConnected || !body[0].contains(searchForm[0]))) retire();
            return !retired;
        }

        // Wagtail supports both Bootstrap modal and dialog-backed ModalWorkflow.
        closeTarget.on('hide.bs.modal.castMediaChooser w-dialog:hide.castMediaChooser', retire);
        var observer = new MutationObserver(isCurrent);
        observer.observe(body[0], {childList: true});
        // ModalWorkflow removes a previous modal when opening a replacement.
        if (closeTarget[0] && closeTarget[0].parentNode) {
            observer.observe(closeTarget[0].parentNode, {childList: true});
        }
        modal.castMediaChooserCleanup = retire;

        function ajaxifyLinks(context) {
            $('a.media-choice', context).on('click.castMediaChooser', function(e) {
                e.preventDefault();
                if (!isCurrent()) return;
                var intent = newIntent();
                resultsRequest = $.ajax({
                    url: this.href,
                    dataType: 'text',
                    success: function(response) {
                        if (!isCurrent() || intent !== generation) return;
                        resultsRequest = null;
                        retire();
                        modal.loadResponseText(response);
                    },
                    error: function() {
                        if (!isCurrent() || intent !== generation) return;
                        resultsRequest = null;
                        $('#search-results', body).prepend(
                            $('<p class="help-block help-critical"></p>').text(jsonData.error_message)
                        );
                    }
                });
            });
            $('.pagination a', context).on('click.castMediaChooser', function(e) {
                e.preventDefault();
                setPage(this.getAttribute('data-page'));
            });
        }

        function fetchResults(requestData) {
            if (!isCurrent()) return;
            var intent = newIntent();
            resultsRequest = $.ajax({
                url: searchUrl,
                data: requestData,
                success: function(data) {
                    if (!isCurrent() || intent !== generation) return;
                    resultsRequest = null;
                    $('#search-results', body).html(data);
                    ajaxifyLinks($('#search-results', body));
                }
            });
        }

        function search() {
            currentTag = null;
            fetchResults({
                q: $('#id_q', body).val(),
                collection_id: $('#collection_chooser_collection_id', body).val()
            });
            return false;
        }

        function setPage(page) {
            var params = {p: page};
            if ($('#id_q', body).val().length) params.q = $('#id_q', body).val();
            if (currentTag) params.tag = currentTag;
            params.collection_id = $('#collection_chooser_collection_id', body).val();
            fetchResults(params);
        }

        ajaxifyLinks(body);
        uploadForm.on('submit.castMediaChooser', function(e) {
            e.preventDefault();
            if (!isCurrent() || uploadAttempt) return false;
            var title = uploadForm.find('[name="title"], [name$="-title"]');
            if (title.val() === '') {
                var field = title.closest('li');
                if (!field.hasClass('error')) {
                    field.addClass('error');
                    title.after('<p class="error-message"><span>This field is required.</span></p>');
                }
                return false;
            }
            var attempt = {};
            uploadAttempt = attempt;
            submitButtons.prop('disabled', true);
            attempt.request = $.ajax({
                url: this.action,
                data: new FormData(this),
                processData: false,
                contentType: false,
                type: 'POST',
                dataType: 'text',
                success: function(response) {
                    if (!isCurrent() || uploadAttempt !== attempt) return;
                    uploadAttempt = null;
                    retire();
                    modal.loadResponseText(response);
                },
                error: function(response, textStatus, errorThrown) {
                    if (!isCurrent() || uploadAttempt !== attempt) return;
                    uploadAttempt = null;
                    submitButtons.prop('disabled', false);
                    var error = $('<div class="help-block help-critical"></div>');
                    error.append($('<strong></strong>').text(jsonData.error_label + ': '));
                    error.append(document.createTextNode(jsonData.error_message + ' ' + errorThrown + ' - ' + response.status));
                    uploadForm.append(error);
                }
            });
            return false;
        });

        searchForm.on('submit.castMediaChooser', search);
        $('#id_q', body).on('input.castMediaChooser', function() {
            if (!isCurrent()) return;
            newIntent();
            searchTimer = setTimeout(search, 200);
        });
        $('#collection_chooser_collection_id', body).on('change.castMediaChooser', search);
        $('a.suggested-tag', body).on('click.castMediaChooser', function() {
            currentTag = $(this).text();
            $('#id_q', body).val('');
            fetchResults({tag: currentTag, collection_id: $('#collection_chooser_collection_id', body).val()});
            return false;
        });

        // Only the video file names the item; the poster image must not.
        var fileWidget = uploadForm.find('input[type="file"][name="original"], input[type="file"][name$="-original"]');
        fileWidget.on('change.castMediaChooser', function() {
            var titleWidget = uploadForm.find('[name="title"], [name$="-title"]');
            if (titleWidget.val() === '') {
                var parts = $(this).val().split('\\');
                titleWidget.val(parts[parts.length - 1]);
            }
        });
        uploadForm.find('[name="tags"], [name$="-tags"]').tagit({autocomplete: {source: jsonData.tag_autocomplete_url}});
    },
    'video_chosen': function(modal, jsonData) {
        if (modal.castMediaChooserCleanup) modal.castMediaChooserCleanup();
        modal.respond('videoChosen', jsonData.result);
        modal.close();
    },
    'select_format': function(modal) {
        if (modal.castMediaChooserCleanup) modal.castMediaChooserCleanup();
        $('form', modal.body).on('submit', function() {
            $.post(this.action, $(this).serialize(), modal.loadResponseText, 'text');
            return false;
        });
    }
};
