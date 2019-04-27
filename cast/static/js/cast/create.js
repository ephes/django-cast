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

// get cast prefix from schema
console.log('schema: ', schema);
let cast_prefix = Object.keys(schema.content).slice(-1)[0];
if (cast_prefix === 'api') {
  cast_prefix = false;
}

function onFilepondUploadError(response) {
  console.log("on upload error: ", response);
}

function onFilepondUploadSuccess(response) {
  console.log("on upload success: ", response);
  refreshMedia();
  return response;
}

function onFilepondRevertSuccess(response) {
  console.log("on revert success: ", response);
  refreshMedia();
  return response;
}

// Filepond
$(function(){
  // First register any plugins
  $.fn.filepond.registerPlugin(FilePondPluginImagePreview);
  /*
  $.fn.filepond.registerPlugin(FilePondPluginFileValidateType);
  $.fn.filepond.registerPlugin(FilePondPluginImageExifOrientation);
  $.fn.filepond.registerPlugin(FilePondPluginImageCrop);
  $.fn.filepond.registerPlugin(FilePondPluginImageResize);
  $.fn.filepond.registerPlugin(FilePondPluginImageTransform);
  $.fn.filepond.registerPlugin(FilePondPluginImageEdit);
  */

  // Turn input element into a pond
  $('.my-pond').filepond();

  // Settings
  $('.my-pond').filepond('allowMultiple', true);
  $('.my-pond').filepond('instantUpload', true);
  $('.my-pond').filepond('acceptedFileTypes', 'image/jpeg, image/png, audio/*, video/*');

  const serverConfig = {
    process: {
      url: '/uploads/process/cast',
      onerror: onFilepondUploadError,
      onload: onFilepondUploadSuccess,
    },
    fetch: null,
    revert: {
      url: '/uploads/revert/',
      method: 'POST',
      onload: onFilepondRevertSuccess,
    },
  }

  $('.my-pond').filepond('server', serverConfig);

  // Listen for addfile event
  $('.my-pond').on('FilePond:addfile', function(e) {
      console.log('file added event', e);
  });

});

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
      .addClass('cast-gallery-thumbnail')
      .addClass('cast-gallery-image-markable')
      .attr({src: image.thumbnail_src, id: image.id})

    var thumbDiv = $('<div></div>')
      .addClass('cast-gallery-preview')
      .append(img)
    preview.append(thumbDiv)
  }
  $('.cast-gallery-image-markable').click(markableImageHandler)
}

function refreshImages() {
  imagesAction = ['api', 'images', 'list']
  console.log('cast prefix: ', cast_prefix);
  if (cast_prefix) {
    imagesAction.unshift(cast_prefix);
  }
  client.action(schema, imagesAction).then(function (result) {
    $('#preview-images').empty();
    showExistingImages(result.results)
    if (result.results.length > 0) {
      $('#insert-images').show();
    } else {
      $('#insert-images').hide();
    }
  })
}

refreshImages();

var galleries = {}
let galleriesAction = ['api', 'gallery', 'list']
if (cast_prefix) {
  galleriesAction.unshift(cast_prefix);
}
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
    $('.cast-gallery-video-markable.border').each(function () {
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
      videoThumbnail = '/static/img/cast/Video-icon.svg'
    }
    // console.log('video thumbnail: ' + videoThumbnail)
    var videoEl = $('<img></img>')
      .addClass('cast-gallery-thumbnail')
      .addClass('cast-gallery-video-markable')
      .attr({src: videoThumbnail, id: video.id})
      // .attr({src: video.poster_thumbnail, id: video.id})

    var thumbDiv = $('<div></div>')
      .addClass('cast-gallery-preview')
      .append(videoEl)
    preview.append(thumbDiv)
  }
  $('.cast-gallery-video-markable').click(markableVideoHandler)
}

function refreshVideos() {
  videosAction = ['api', 'videos', 'list']
  if (cast_prefix) {
    videosAction.unshift(cast_prefix);
  }
  client.action(schema, videosAction).then(function (result) {
    $('#preview-videos').empty();
    showExistingVideos(result.results)
    if (result.results.length > 0) {
      $('#insert-video').show();
    } else {
      $('#insert-video').hide();
    }
  })
}

refreshVideos();

// get/show existing audios

function markableAudioHandler () {
  var el = $(this)
  console.log('clicked audio: ' + el.attr('id'))
  if (el.hasClass('border')) {
    el.removeClass('border border-primary')
  } else {
    $('.cast-gallery-audio-markable.border').each(function () {
      $(this).removeClass('border border-primary')
    })
    el.addClass('border border-primary')
  }
}


function showExistingAudios (audios) {
  console.log(audios.length)
  var preview = $('#preview-audios')
  for (var i = 0; i < audios.length; i++) {
    let audio = audios[i]
    const audioThumbnail = '/static/img/cast/Audio-icon.svg'
    let audioEl = $('<img></img>')
      .addClass('cast-gallery-thumbnail')
      .addClass('cast-gallery-audio-markable')
      .attr({src: audioThumbnail, id: audio.id})
    let audioNameEl = $(`<div>${audio.name} ${audio.file_formats}</div>`)
      .addClass('cast-gallery-thumbnail')
      .addClass('cast-gallery-audio-markable')
      .attr({id: audio.id})
    var thumbDiv = $('<div></div>')
      .addClass('cast-gallery-preview')
      //.append(audioEl)
      .append(audioNameEl)
    preview.append(thumbDiv)
  }
  $('.cast-gallery-audio-markable').click(markableAudioHandler)
}

function refreshAudios() {
  audiosAction = ['api', 'audio', 'list']
  console.log('cast prefix audios: ', cast_prefix);
  if (cast_prefix) {
    audiosAction.unshift(cast_prefix);
  }
  client.action(schema, audiosAction).then(function (result) {
    $('#preview-audios').empty();
    console.log("audios list: ", result.results)
    showExistingAudios(result.results)
    let audio_select = $('select[name=podcast_audio]');
    if (audio_select.length > 0) {
      // found podcast audio select element
      let choose_lookup = {}
      for (let child of audio_select.children()) {
        if (child.value) {
          choose_lookup[child.value] = child;
        }
      }
      for (let item of result.results) {
        if (!(item.id in choose_lookup)) {
          // add newly uploaded audio to select as option
          let option_el_text = '<option value="' + item.id + '">';
          option_el_text = option_el_text + item.id + " - " + item.name + '</option>';
          $(audio_select).append(option_el_text);
        }
      }
    }
    if (result.results.length > 0) {
      $('#insert-audio').show();
    } else {
      $('#insert-audio').hide();
    }
  })
}

refreshAudios();

function refreshMedia() {
  refreshImages();
  refreshVideos();
  refreshAudios();
}

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
    let action = ['api', 'gallery', 'create']
    if (cast_prefix) {
      action.unshift(cast_prefix);
    }
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
  var marked = $('.cast-gallery-image-markable.border')
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
  var marked = $('.cast-gallery-video-markable.border')
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

function handleAudioInsert () {
  console.log('handle audio insert')
  var marked = $('.cast-gallery-audio-markable.border')
  var audioPks = []
  for (var i = 0; i < marked.length; i++) {
    audioPks.push(parseInt($(marked[i]).attr('id')))
  }
  var ckForm = getCkEditorInstance()
  if (audioPks.length === 0) {
    console.log('no audio media to add')
  } else if (audioPks.length === 1) {
    var audioPk = audioPks[0]
    var templateTag = '{' + '% ' + 'audio ' + audioPk + ' %' + '}'
    ckForm.insertHtml(templateTag)
  } else {
    console.log('multiple audios not supported yet')
  }
}

$('#insert-audio').click(handleAudioInsert)

