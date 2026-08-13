from django.urls import include, path, reverse
from wagtail import hooks
from wagtail.admin.menu import MenuItem
from wagtail.snippets.models import register_snippet

from .snippet_viewsets import IOT_SNIPPET_VIEWSETS


for snippet_viewset in IOT_SNIPPET_VIEWSETS:
    register_snippet(snippet_viewset)


class IoTMenuItem(MenuItem):
    def is_active(self, request):
        return request.path.startswith(self.url)


@hooks.register("register_admin_menu_item")
def register_iot_menu_item():
    return IoTMenuItem(
        "IoT",
        reverse("iot:dashboard"),
        icon_name="cog",
        order=240,
        name="iot-menu",
    )


@hooks.register("register_admin_urls")
def register_iot_admin_urls():
    from . import admin_urls

    return [
        path("iot/", include((admin_urls, "iot"), namespace="iot")),
    ]
