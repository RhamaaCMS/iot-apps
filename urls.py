from django.urls import path
from . import views

app_name = 'IoT'

urlpatterns = [
    path('', views.index, name='index'),
]
