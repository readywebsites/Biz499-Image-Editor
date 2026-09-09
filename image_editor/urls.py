"""
URL configuration for image_editor project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from django.views.generic import TemplateView, RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('editorapp.urls')),
    
    # Redirect bare /static/ or /static to root /
    path('static/', RedirectView.as_view(url='/', permanent=False)),
    
    # Serve built frontend static assets directly from dist & dist/assets
    path('favicon.svg', serve, {'document_root': str(settings.BASE_DIR / 'dist'), 'path': 'favicon.svg'}),
    path('icons.svg', serve, {'document_root': str(settings.BASE_DIR / 'dist'), 'path': 'icons.svg'}),
    re_path(r'^static/(?P<path>.+)$', serve, {'document_root': str(settings.BASE_DIR / 'dist')}),
    re_path(r'^assets/(?P<path>.*)$', serve, {'document_root': str(settings.BASE_DIR / 'dist' / 'assets')}),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# SPA Catch-all: Route everything else to the React index.html, excluding Django admin, API, and media routes
urlpatterns += [
    re_path(r'^(?!admin(?:/|$)|api(?:/|$)|media(?:/|$)).*$', TemplateView.as_view(template_name='index.html')),
]
