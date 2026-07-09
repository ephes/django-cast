from wagtail import blocks


class CustomCalloutBlock(blocks.CharBlock):
    pass


class WeeknoteLinkBlock(blocks.StructBlock):
    category = blocks.CharBlock(required=True)
    kind = blocks.ChoiceBlock(choices=[("article", "Article"), ("video", "Video")], required=True)
    title = blocks.CharBlock(required=True)
    url = blocks.URLBlock(required=True)
    source = blocks.CharBlock(required=False)
    source_url = blocks.URLBlock(required=False)
    description = blocks.RichTextBlock(required=False)


class RaisingToPythonBlock(blocks.CharBlock):
    def to_python(self, value):
        raise ValueError("custom conversion failed")


def overview_callout_block():
    return "overview_callout", CustomCalloutBlock()


def detail_callout_block():
    return "detail_callout", CustomCalloutBlock()


def repeated_detail_callout_block():
    return "detail_callout", blocks.TextBlock()


def weeknote_links_block():
    return "weeknote_links", blocks.ListBlock(WeeknoteLinkBlock())


def detail_weeknote_links_block():
    return "weeknote_links", blocks.ListBlock(WeeknoteLinkBlock())


def raising_to_python_block():
    return "raising_custom", RaisingToPythonBlock()


def paragraph_collision_block():
    return "paragraph", CustomCalloutBlock()


def invalid_shape_block():
    return ("invalid_shape",)


def non_string_name_block():
    return 1, CustomCalloutBlock()


def empty_name_block():
    return " ", CustomCalloutBlock()


def invalid_block_instance():
    return "invalid_block", object()


def raising_block():
    raise RuntimeError("factory failed")


not_callable = object()
