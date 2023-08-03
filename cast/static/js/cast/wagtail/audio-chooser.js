function createAudioChooser(id) {
    let chooserElement = $('#' + id + '-chooser');
    let audioTitle = chooserElement.find('.title');
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
            audioTitle.text(newState.title);
            editLink.attr('href', newState.edit_link);
            chooserElement.removeClass('blank');
            state = newState;
        },
        openChooserModal: () => {
            // eslint-disable-next-line no-undef, new-cap
            ModalWorkflow({
                url: window.chooserUrls.audioChooser,
                // eslint-disable-next-line no-undef
                onload: AUDIO_CHOOSER_MODAL_ONLOAD_HANDLERS,
                responses: {
                    audioChosen: (result) => {
                        chooser.setState(result);
                    },
                },
            });
        },
        getTextLabel: (opts) => {
            if (!audioTitle.text()) return '';
            let maxLength = opts && opts.maxLength,
                result = audioTitle.text();
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
