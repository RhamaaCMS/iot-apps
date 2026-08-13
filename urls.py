from django.urls import path
from . import views

app_name = 'IoT'

urlpatterns = [
    path('', views.index, name='index'),
    path('api/v1/provision/', views.provision, name='provision'),
    path('api/v2/registry/', views.registry, name='registry'),
]
