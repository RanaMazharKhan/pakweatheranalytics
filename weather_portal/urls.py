"""URL configuration for weather_portal project."""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from django.views.generic import TemplateView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('google0574e06f59cbf9df.html', TemplateView.as_view(template_name='google0574e06f59cbf9df.html', content_type='text/html')),
    path('', include('weather.urls')),
    path('accounts/', include('accounts.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
