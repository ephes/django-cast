function createVideoChooser(id) {
    var chooserElement = $('#' + id + '-chooser');
    var videoTitle = chooserElement.find('.title');
    var input = $('#' + id);
    var editLink = chooserElement.find('.edit-link');

    $('.action-choose', chooserElement).on('click', function() {
        ModalWorkflow({
            url: window.chooserUrls.videoChooser,
            onload: VIDEO_CHOOSER_MODAL_ONLOAD_HANDLERS,
            responses: {
                videoChosen: function(videoData) {
                    input.val(videoData.id);
                    videoTitle.text(videoData.title);
                    chooserElement.removeClass('blank');
                    editLink.attr('href', videoData.edit_link);
                }
            }
        });
    });

    $('.action-clear', chooserElement).on('click', function() {
        input.val('');
        chooserElement.addClass('blank');
    });
}
