from django.urls import include, path
from rest_framework.routers import DefaultRouter
from sample_app import views

router = DefaultRouter()
router.register(r"books-set", views.BookViewSet, basename="book-set")

urlpatterns = [
    path("books-fbv/", views.book_list_fbv, name="book-list-fbv"),
    path("books-cbv/<int:pk>/", views.BookDetailCBV.as_view(), name="book-detail-cbv"),
    path("books-drf/", views.BookListAPIView.as_view(), name="book-list-drf"),
    path("", include(router.urls)),
]