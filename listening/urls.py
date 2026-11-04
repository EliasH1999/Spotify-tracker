from django.urls import path

from . import views

app_name = "listening"
urlpatterns = [path("", views.dashboard, name="dashboard")]
