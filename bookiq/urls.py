from django.contrib import admin
from django.http import JsonResponse
from django.urls import path, include
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

def health(request):
    return JsonResponse({"status": "ok"})

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('users.urls')), # Auth endpoints
    path('api/', include('books.urls')), # Core API
    path('api/analytics/', include('books.urls_analytics')), # Analytics
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'), # OpenAPI schema (raw JSON/YAML)
    
    # Swagger UI
    path(
        'api/docs/',
        SpectacularSwaggerView.as_view(url_name='schema'),
        name='swagger-ui'
    ),

    # ReDoc (alternative clean docs view)
    path(
        'api/redoc/',
        SpectacularRedocView.as_view(url_name='schema'),
        name='redoc'
    ),
    path("health/", health),
]

handler404 = 'books.exceptions.handler_404'
handler500 = 'books.exceptions.handler_500'