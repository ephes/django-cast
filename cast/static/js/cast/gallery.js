/* global $ */

var curImage = null
var modalImage = $('.modal-image')
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

function setModalImage (el) {
  curImage = el
  modalImage.attr('src', curImage.attr('src')).attr('srcset', curImage.attr('srcset'))
  modalImage.parent().attr('href', curImage.parent().data("full"))
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
