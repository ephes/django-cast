from cast.models import PostCategory


def test_post_category_name():
    category = PostCategory(name="Test Category", slug="test-category")
    assert str(category) == "Test Category"
