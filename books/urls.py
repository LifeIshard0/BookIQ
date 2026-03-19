from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import BookViewSet, ImportJobViewSet

router = DefaultRouter()
router.register(r'books', BookViewSet, basename='book')
router.register(r'imports', ImportJobViewSet, basename='import')

urlpatterns = [
    path('', include(router.urls)),
]
