from django.urls import include, path, reverse
from wagtail import hooks
from wagtail.admin.menu import Menu, MenuItem, SubmenuMenuItem
from wagtail.snippets.models import register_snippet

from .snippet_viewsets import IOT_SNIPPET_VIEWSETS


for snippet_viewset in IOT_SNIPPET_VIEWSETS:
    register_snippet(snippet_viewset)


class SuperuserMenuItem(MenuItem):
    def is_shown(self, request):
        return request.user.is_superuser


def _iot_submenu_items():
    return [
        MenuItem(
            "Ringkasan",
            reverse("iot:dashboard"),
            icon_name="home",
            order=10,
            name="iot-menu-summary",
        ),
        MenuItem(
            "Organisasi",
            reverse("iot:panel_organizations"),
            icon_name="group",
            order=20,
            name="iot-menu-organizations",
        ),
        MenuItem(
            "Pengguna & organisasi",
            reverse("iot:panel_memberships"),
            icon_name="user",
            order=30,
            name="iot-menu-memberships",
        ),
        SuperuserMenuItem(
            "Device Profiles",
            reverse("wagtailsnippets_iot_deviceprofile:list"),
            icon_name="tasks",
            order=35,
            name="iot-menu-device-profiles",
        ),
        MenuItem(
            "Perangkat",
            reverse("iot:panel_devices"),
            icon_name="radio-full",
            order=40,
            name="iot-menu-devices",
        ),
        SuperuserMenuItem(
            "Firmware Versions",
            reverse("wagtailsnippets_iot_firmwareversion:list"),
            icon_name="doc-full",
            order=45,
            name="iot-menu-firmware",
        ),
        MenuItem(
            "OTA",
            reverse("iot:panel_ota"),
            icon_name="upload",
            order=50,
            name="iot-menu-ota",
        ),
    ]


@hooks.register("register_admin_menu_item")
def register_iot_menu_item():
    return SubmenuMenuItem(
        "IoT",
        Menu(items=_iot_submenu_items()),
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
