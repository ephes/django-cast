def test_render_post_description_uses_post_repository_and_default_formatting(mocker, simple_request):
    from cast.presenters import render_post_description

    post = mocker.Mock()
    repository = mocker.sentinel.repository
    post.get_repository.return_value = repository
    post.serve.return_value.rendered_content = "<h1>foo</h1>\n"

    description = render_post_description(post, request=simple_request)

    assert description == "&lt;h1&gt;foo&lt;/h1&gt;"
    post.get_repository.assert_called_once_with(simple_request, {})
    post.serve.assert_called_once_with(
        simple_request,
        render_detail=False,
        repository=repository,
        render_for_feed=True,
        local_template_name="post_body.html",
    )


def test_render_post_description_uses_supplied_repository_and_raw_formatting(mocker, simple_request):
    from cast.presenters import render_post_description

    post = mocker.Mock()
    repository = mocker.sentinel.repository
    post.serve.return_value.rendered_content = "<p>foo</p>\n"

    description = render_post_description(
        post,
        request=simple_request,
        render_detail=True,
        render_for_feed=False,
        escape_html=False,
        remove_newlines=False,
        repository=repository,
    )

    assert description == "<p>foo</p>\n"
    post.get_repository.assert_not_called()
    post.serve.assert_called_once_with(
        simple_request,
        render_detail=True,
        repository=repository,
        render_for_feed=False,
        local_template_name="post_body.html",
    )
