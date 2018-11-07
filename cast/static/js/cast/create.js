/* global $ */
const CKEDITOR = window.CKEDITOR
const coreapi = window.coreapi
const schema = window.schema

var csrfToken = $('input[name=csrfmiddlewaretoken]').attr('value')
console.log('csrftoken: ', csrfToken)
document.cookie = 'csrftoken=' + csrfToken

let auth = new coreapi.auth.SessionAuthentication({
  csrfCookieName: 'csrftoken',
  csrfHeaderName: 'X-CSRFToken'
})
let client = new coreapi.Client({auth: auth})
console.log(client)

// get/show existing images/galleries

function markableImageHandler () {
  let el = $(this)
  console.log('clicked image: ' + el.attr('id'))
  if (el.hasClass('border')) {
    el.removeClass('border border-primary')
  } else {
    el.addClass('border border-primary')
  }
}

function showExistingImages (images) {
  console.log(images.length)
  var preview = $('#preview-images')
  for (var i = 0; i < images.length; i++) {
    let image = images[i]
    var img = $('<img></img>')
      .addClass('gallery-thumbnail')
      .addClass('gallery-image-markable')
      .attr({src: image.thumbnail_src, id: image.id})

    var thumbDiv = $('<div></div>')
      .addClass('gallery-preview')
      .append(img)
    preview.append(thumbDiv)
  }
  $('.gallery-image-markable').click(markableImageHandler)
}

let imagesAction = ['cast', 'api', 'images', 'list']
client.action(schema, imagesAction).then(function (result) {
  console.log(result)
  showExistingImages(result.results)
})

var galleries = {}
let galleriesAction = ['cast', 'api', 'gallery', 'list']
client.action(schema, galleriesAction).then(function (result) {
  var results = result.results
  console.log('galleries', result)
  for (var i = 0; i < results.length; i++) {
    let images = results[i]['images'].sort().join()
    console.log(images)
    let galleryId = results[i]['id']
    galleries[images] = galleryId
  }
})

// get/show existing videos

function markableVideoHandler () {
  var el = $(this)
  console.log('clicked video: ' + el.attr('id'))
  if (el.hasClass('border')) {
    el.removeClass('border border-primary')
  } else {
    $('.gallery-video-markable.border').each(function () {
      $(this).removeClass('border border-primary')
    })
    el.addClass('border border-primary')
  }
}

function showExistingVideos (videos) {
  console.log(videos.length)
  var preview = $('#preview-videos')
  for (var i = 0; i < videos.length; i++) {
    var video = videos[i]
    var videoThumbnail = video.poster_thumbnail
    if (!videoThumbnail) {
      videoThumbnail = '/static/images/Video-icon.svg'
    }
    // console.log('video thumbnail: ' + videoThumbnail)
    var videoEl = $('<img></img>')
      .addClass('gallery-thumbnail')
      .addClass('gallery-video-markable')
      .attr({src: videoThumbnail, id: video.id})
      // .attr({src: video.poster_thumbnail, id: video.id})

    var thumbDiv = $('<div></div>')
      .addClass('gallery-preview')
      .append(videoEl)
    preview.append(thumbDiv)
  }
  $('.gallery-video-markable').click(markableVideoHandler)
}

let videosAction = ['cast', 'api', 'videos', 'list']
client.action(schema, videosAction).then(function (result) {
  console.log(result)
  showExistingVideos(result.results)
})

function replaceWithUploadedImage (imagePk, img) {
  let action = ['cast', 'api', 'images', 'read']
  let params = {id: imagePk}
  console.log('params', params)
  client.action(schema, action, params).then(function (result) {
    console.log('get detail for image ' + imagePk, result)
    $(img).attr({id: imagePk, src: result.thumbnail_src})
      .removeClass('image-obj')
      .addClass('gallery-image-markable')
    $(img).click(markableImageHandler)
  })
}

function replaceWithUploadedVideo (videoPk, video) {
  let action = ['cast', 'api', 'videos', 'read']
  let params = {id: videoPk}
  console.log('params', params)
  client.action(schema, action, params).then(function (result) {
    console.log('get detail for video ' + videoPk, result)
    $(video).attr({id: videoPk, src: result.original})
      .removeClass('video-obj')
      .addClass('gallery-video-markable')
    $(video).click(markableVideoHandler)
  })
}

var runningUploads = 0

function fileUpload (thumb, file, progressBar) {
  var xhr = new window.XMLHttpRequest()
  console.log('file upload:', thumb, file)
  xhr.upload.addEventListener('progress', function (e) {
    if (e.lengthComputable) {
      var percentage = Math.round((e.loaded * 100) / e.total)
      console.log('progress: ' + percentage)
      progressBar.attr({
        'aria-valuenow': percentage,
        'style': 'width: ' + percentage + '%'
      })
    }
  }, false)

  var uploadUrl = '/cast/api/upload_image/'
  let tagName = $(thumb).prop('tagName')
  console.log('tagname: ', tagName)
  if (tagName === 'VIDEO') {
    uploadUrl = '/cast/api/upload_video/'
  }

  xhr.open('POST', uploadUrl)
  xhr.setRequestHeader('X-CSRFToken', csrfToken)
  var formData = new window.FormData()
  formData.append('original', file)
  xhr.enctype = 'mutlipart/form-data'

  xhr.onreadystatechange = function () {
    if (xhr.readyState === window.XMLHttpRequest.DONE && xhr.status === 201) {
      console.log('request finished:')
      var mediaPk = xhr.responseText
      console.log('media id: ', mediaPk)
      progressBar.attr({
        'aria-valuenow': '100',
        'style': 'width: 100%'
      })
      progressBar.remove()
      if (tagName === 'VIDEO') {
        replaceWithUploadedVideo(mediaPk, thumb)
      } else {
        replaceWithUploadedImage(mediaPk, thumb)
      }
      runningUploads = runningUploads - 1
    }
  }

  xhr.send(formData)
}

function waitForUpload (thumb, file, progressBar) {
  if (runningUploads < 2) {
    runningUploads = runningUploads + 1
    console.log('wait for upload: upload')
    fileUpload(thumb, file, progressBar)
  } else {
    setTimeout(waitForUpload, 500, thumb, file, progressBar)
    console.log('wait for upload: wait')
  }
}

function sendFiles (uploadFiles, uploadProgress, className) {
  console.log('sendFiles..', className)
  var files = document.querySelectorAll('.' + className)
  for (var i = 0; i < files.length; i++) {
    var file = uploadFiles[i]
    var progressBar = uploadProgress[i]
    waitForUpload(files[i], file, progressBar)
    // fileUpload(files[i], file, progressBar)
  }
}

function getThumbnail (tagName, className) {
  var thumb = $('<' + tagName + ' />')
    .addClass('gallery-thumbnail ' + className)

  var progressBar = $('<div></div>')
    .addClass('progress-bar')
    .attr({
      role: 'progressbar',
      'aria-valuenow': '0',
      'aria-valuemin': '0',
      'aria-valuemax': '100'
    })

  var progressDiv = $('<div></div>')
    .addClass('progress gallery-progress-bar')
    .append(progressBar)

  var thumbDiv = $('<div></div>')
    .addClass('gallery-preview')
    .append(thumb)
    .append(progressDiv)
  return [thumb, thumbDiv, progressBar]
}

function handleImageFiles () {
  console.log('handleImageFiles')
  var files = $(this.files)
  console.log(files)
  var preview = $('#preview-images')
  var uploadFiles = []
  var uploadProgress = []
  for (var i = 0, numFiles = files.length; i < numFiles; i++) {
    var file = files[i]
    console.log(file.name)
    console.log(file.size)
    console.log(file.type)
    var imageType = /^image\//

    if (!imageType.test(file.type)) {
      continue
    }
    var [thumb, thumbDiv, progressBar] = getThumbnail('img', 'image-obj')

    uploadFiles.push(file)
    uploadProgress.push(progressBar)
    preview.prepend(thumbDiv)

    var reader = new window.FileReader()
    reader.onload = (function (aImg) {
      return function (e) {
        aImg.attr({src: e.target.result})
      }
    })(thumb)
    reader.readAsDataURL(file)
  }
  sendFiles(uploadFiles, uploadProgress, 'image-obj')
}

$('#image-input').on('change', handleImageFiles)

function handleVideoFiles () {
  console.log('handleVideoFiles')
  var files = $(this.files)
  console.log(files)
  var preview = $('#preview-videos')
  var uploadFiles = []
  var uploadProgress = []
  for (var i = 0, numFiles = files.length; i < numFiles; i++) {
    var file = files[i]
    console.log(file.name)
    console.log(file.size)
    console.log(file.type)
    var videoType = /^video\//

    if (!videoType.test(file.type)) {
      continue
    }
    var [thumb, thumbDiv, progressBar] = getThumbnail('video', 'video-obj')

    uploadFiles.push(file)
    uploadProgress.push(progressBar)
    preview.prepend(thumbDiv)

    var reader = new window.FileReader()
    reader.onload = (function (aImg) {
      return function (e) {
        aImg.attr({src: e.target.result})
      }
    })(thumb)
    reader.readAsDataURL(file)
  }
  sendFiles(uploadFiles, uploadProgress, 'video-obj')
}

$('#video-input').on('change', handleVideoFiles)

function getCkEditorInstance () {
  for (var instanceName in CKEDITOR.instances) {
    var ckForm = CKEDITOR.instances[instanceName]
  }
  return ckForm
}

function addGallery (imagePks, ckForm) {
  var images = imagePks.slice().sort().join()
  if (images in galleries) {
    var templateTag = '{' + '% ' + 'gallery ' + galleries[images] + ' %' + '}'
    ckForm.insertHtml(templateTag)
  } else {
    let action = ['cast', 'api', 'gallery', 'create']
    let params = {'images': imagePks}
    console.log('params', params)
    client.action(schema, action, params).then(function (result) {
      console.log('created galleries ', result)
      let galleryPk = result['id']
      var templateTag = '{' + '% ' + 'gallery ' + galleryPk + ' %' + '}'
      ckForm.insertHtml(templateTag)
      galleries[images] = galleryPk
    })
  }
  console.log(galleries[images])
}

function handleImageInsert () {
  console.log('handle image insert')
  var marked = $('img.border')
  var imagePks = []
  for (var i = 0; i < marked.length; i++) {
    imagePks.push(parseInt($(marked[i]).attr('id')))
  }
  var ckForm = getCkEditorInstance()
  if (imagePks.length === 0) {
    console.log('no image media to add')
  } else if (imagePks.length === 1) {
    var imgPk = imagePks[0]
    var templateTag = '{' + '% ' + 'image ' + imgPk + ' %' + '}'
    ckForm.insertHtml(templateTag)
  } else {
    addGallery(imagePks, ckForm)
  }
}

$('#insert-images').click(handleImageInsert)

function handleVideoInsert () {
  console.log('handle video insert')
  var marked = $('.gallery-video-markable.border')
  var videoPks = []
  for (var i = 0; i < marked.length; i++) {
    videoPks.push(parseInt($(marked[i]).attr('id')))
  }
  var ckForm = getCkEditorInstance()
  if (videoPks.length === 0) {
    console.log('no video media to add')
  } else if (videoPks.length === 1) {
    var videoPk = videoPks[0]
    var templateTag = '{' + '% ' + 'video ' + videoPk + ' %' + '}'
    ckForm.insertHtml(templateTag)
  } else {
    console.log('multiple videos not supported yet')
  }
}

$('#insert-video').click(handleVideoInsert)
