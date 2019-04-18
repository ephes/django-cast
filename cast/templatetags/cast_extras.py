from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag(takes_context=True)
def image(context, pk):
    image = context["image"][pk]
    image_tag = (
        '<a href="{full}">'
        '  <img class="cast-image" src="{src}" srcset="{srcset}" sizes="100vw"></img>'
        "</a>"
    ).format(srcset=image.get_srcset(), src=image.img_xs.url, full=image.img_full.url)
    return mark_safe(image_tag)


@register.simple_tag(takes_context=True)
def video(context, pk):
    video = context["video"][pk]
    if video.poster:
        poster_url = video.poster.url
    else:
        poster_url = "/static/img/cast/Video-icon.svg"
    video_tag = (
        '<video class="cast-video" preload="auto" controls poster="{poster}">'
        '  <source src="{src}" type="video/mp4">'
        "  your browser does not support the video tag"
        "</video>"
    ).format(src=video.original.url, poster=poster_url)
    return mark_safe(video_tag)


@register.simple_tag(takes_context=True)
def audio(context, pk):
    audio_tag = f'<div id="audio_{pk}"></div>'
    return mark_safe(audio_tag)


# gallery tag


def get_modal_trigger(gallery_key, image, prev_img, next_img):
    srcset = image.get_srcset()
    prev_id = "img-{}".format(prev_img.pk) if prev_img is not None else "false"
    next_id = "img-{}".format(next_img.pk) if next_img is not None else "false"
    thumbnail_tag = (
        '<img id="img-{img_id}" class="cast-gallery-thumbnail" src="{src}" '
        'srcset="{srcset}" data-prev="{prev}" data-next="{next}" '
        'data-full="{full}"></img>'
    ).format(
        img_id=image.pk,
        prev=prev_id,
        next=next_id,
        srcset=srcset,
        src=image.img_xs.url,
        full=image.img_full.url,
    )
    return """
        <a src="#" class="cast-gallery-modal" data-toggle="modal" data-target="#galleryModal{key}">
            {thumbnail_tag}
        </a>
    """.format(
        thumbnail_tag=thumbnail_tag, key=gallery_key
    )


def get_image_thumb(image):
    srcset = image.get_srcset()
    thumbnail_tag = (
        '<img class="cast-gallery-thumbnail" src={src} ' 'srcset="{srcset}"</img>'
    ).format(src=image.img_xs.url, srcset=srcset)
    return """
        <a href="{full}"">
            {thumbnail_tag}
        </a>
    """.format(
        thumbnail_tag=thumbnail_tag, full=image.img_full.url
    )


def get_modal_tmpl():
    return """
        {thumbs}
        <!-- Modal -->
        <div class="modal fade" id="galleryModal{key}" tabindex="-1" role="dialog"
             aria-labelledby="galleryModalLabel" aria-hidden="true">
            <div class="modal-dialog modal-lg cast-gallery-lg" role="document">
                <div class="modal-content cast-gallery-content">
                    <div class="modal-header cast-gallery-header">
                        <button type="button" class="close" data-dismiss="modal" aria-label="Close">
                            <span aria-hidden="true">&times;</span>
                            </button>
                        </div>
                        <div class="modal-body cast-gallery-body">
                        <a href=""><img class="modal-image cast-image" src="" srcset="" sizes="100vw"></img></a>
                    </div>
                    <div class="modal-footer cast-gallery-footer">
                        </div>
                    </div>
            </div>
        </div>
    """


def gallery_with_javascript(gallery, post):
    image_thumbs = [
        "<!-- Button trigger modal -->",
        '<div class="cast-gallery-container">',
    ]

    gallery_key = "{}_{}".format(post.pk, gallery.pk)
    prev_img, next_img = None, None
    images = list(gallery.images.all())
    for num, image in enumerate(images, 1):
        if num < len(images):
            next_img = images[num]
        else:
            next_img = None
        image_thumbs.append(get_modal_trigger(gallery_key, image, prev_img, next_img))
        prev_img = image
    image_thumbs.append("</div>")
    thumbs = "\n".join(image_thumbs)
    return get_modal_tmpl().format(thumbs=thumbs, key=gallery_key)


def gallery_without_javascript(gallery):
    image_thumbs = []
    for image in gallery.images.all():
        image_thumbs.append(get_image_thumb(image))
    return "\n".join(image_thumbs)


@register.simple_tag(takes_context=True)
def gallery(context, pk):
    use_javascript = context.get("javascript", True)
    post = context["post"]
    gallery = context["gallery"][pk]
    if use_javascript:
        gallery_html = gallery_with_javascript(gallery, post)
    else:
        gallery_html = gallery_without_javascript(gallery)

    return mark_safe(gallery_html)
