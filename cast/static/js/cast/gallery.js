/* global $ */

var curImage = null
var modalImage = $('.modal-image')
var modalSource = $('.modal-source')
var modalFooter = $('.modal-footer')

function setButtons (curImage, modalFooter) {
  var buttons = ''
  if (curImage.data('prev')) {
    buttons = buttons + '<button id="prev" type="button" class="btn btn-primary">Prev</button>'
  } else {
    buttons = buttons + '<button id="prev" type="button" class="btn btn-primary disabled">Prev</button>'
  }
  if (curImage.data('next')) {
    buttons = buttons + '<button id="next" type="button" class="btn btn-primary">Next</button>'
  } else {
    buttons = buttons + '<button id="next" type="button" class="btn btn-primary disabled">Next</button>'
  }
  modalFooter.html(buttons)
}

function setModalImage(el) {
  curImage = el
  const thumbnailPicture = curImage.parent()
  const thumbnailSource = thumbnailPicture.find('source')
  modalImage.attr('src', curImage.data('modal-src'))
  modalImage.attr('srcset', curImage.data('modal-srcset'))
  modalImage.attr('sizes', curImage.data('modal-sizes'))
  modalImage.attr('width', curImage.data('modal-width'))
  modalImage.attr('height', curImage.data('modal-height'))
  modalImage.attr('alt', curImage.attr('alt'))
  // set link for modal image
  modalImage.parent().parent().attr('href', thumbnailPicture.parent().data("full"))
  // set attributes for modal source
  modalSource.attr('srcset', thumbnailSource.data('modal-srcset'))
  modalSource.attr('sizes', thumbnailSource.data('modal-sizes'))
  // set prev and next buttons
  setButtons(curImage, modalFooter)
}

function replaceImage (which) {
  if (curImage) {
    if (curImage.data(which)) {
      setModalImage($('#' + curImage.data(which)))
    }
  }
}

$('body').on('click', 'button', function () {
  replaceImage($(this).attr('id'))
})

$(document).keydown(function (e) {
  if (e.keyCode === 37) {
    replaceImage('prev')
  }
  if (e.keyCode === 39) {
    replaceImage('next')
  }
})

$('.cast-gallery-modal').click(function (e) {
  setModalImage($(e.target))
})
