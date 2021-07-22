function createVideoChooser(id) {
    var chooserElement = $('#' + id + '-chooser');
    var videoTitle = chooserElement.find('.title');
    var input = $('#' + id);
    var editLink = chooserElement.find('.edit-link');

    let state = null;

    /* define public API functions for the chooser */
    const chooser = {
        getState: () => state,
        getValue: () => state && state.id,
        setState: (newState) => {
            if (newState == null) {
                // return early
                return
            }
            input.val(newState.id);
            videoTitle.text(newState.title);
            editLink.attr('href', newState.edit_url);
            chooserElement.removeClass('blank');
            state = newState;
        },
        openChooserModal: () => {
            // eslint-disable-next-line no-undef, new-cap
            ModalWorkflow({
                url: window.chooserUrls.videoChooser,
                // eslint-disable-next-line no-undef
                onload: VIDEO_CHOOSER_MODAL_ONLOAD_HANDLERS,
                responses: {
                    videoChosen: (result) => {
                        chooser.setState(result);
                    },
                },
            });
        },
    };

    $('.action-choose', chooserElement).on('click', function() {
        chooser.openChooserModal();
    });

    $('.action-clear', chooserElement).on('click', function() {
        input.val('');
        chooserElement.addClass('blank');
    });

    return chooser;
}
