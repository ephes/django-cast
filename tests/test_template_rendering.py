from django.template import Context, Template

import pytest


def test_template_render(test_templ):
    template = Template(test_templ)
    context = Context({})
    result = template.render(context)
    assert "dolor" in result


@pytest.mark.django_db()
def test_blogimage_render_without_context(img_templ, image):
    img_templ = img_templ.format(image.pk)
    template = Template(img_templ)
    context = Context({})
    with pytest.raises(KeyError):
        template.render(context)


@pytest.mark.django_db()
def test_blogimage_render_with_context(img_templ, image):
    img_templ = img_templ.format(image.pk)
    template = Template(img_templ)
    context = Context({"image": {image.pk: image}})
    result = template.render(context)
    assert "<a href" in result
