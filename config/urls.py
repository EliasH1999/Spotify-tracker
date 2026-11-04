"""The project sends dashboard requests to the listening application."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("", include("listening.urls")),
    path("admin/", admin.site.urls),
]
