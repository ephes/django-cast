function createVideoChooser(id) {
    let chooserElement = $('#' + id + '-chooser');
    let videoTitle = chooserElement.find('.title');
    let input = $('#' + id);
    let editLink = chooserElement.find('.edit-link');

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
            editLink.attr('href', newState.edit_link);
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
        getTextLabel: (opts) => {
            if (!videoTitle.text()) return '';
            let maxLength = opts && opts.maxLength,
                result = videoTitle.text();
            if (maxLength && result.length > maxLength) {
                return result.substring(0, maxLength - 1) + '…';
            }
            return result;
        },
        focus: function() {
            $('.action-choose', chooserElement).focus();
        }
    };

    $('.action-choose, [data-chooser-action-choose]', chooserElement).on('click', function() {
        chooser.openChooserModal();
    });

    $('.action-clear', chooserElement).on('click', function() {
        input.val('');
        chooserElement.addClass('blank');
    });

    return chooser;
}
