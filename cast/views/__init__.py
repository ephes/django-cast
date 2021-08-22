from .views import BlogsListView, BlogDetailView, PostsListView, PostDetailView, PostCreateView, PostUpdateView
from .wagtail_video import (
    video_index,
    video_add,
    video_edit,
    video_delete,
    video_chooser,
    get_video_data,
    video_chosen,
    video_chooser_upload,
)

__ALL__ = [
    # old views
    BlogsListView,
    BlogDetailView,
    PostsListView,
    PostDetailView,
    PostCreateView,
    PostUpdateView,
    # wagtail
    video_index,
    video_add,
    video_edit,
    video_delete,
    video_chooser,
    get_video_data,
    video_chosen,
    video_chooser_upload,
]
