from wagtail import blocks


class CustomCalloutBlock(blocks.CharBlock):
    pass


def overview_callout_block():
    return "overview_callout", CustomCalloutBlock()


def detail_callout_block():
    return "detail_callout", CustomCalloutBlock()


def repeated_detail_callout_block():
    return "detail_callout", blocks.TextBlock()


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
