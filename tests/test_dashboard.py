from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone
from wagtail.admin.menu import MenuItem

from ..admin_forms import (
    ExistingUserMembershipForm,
    IoTUserMembershipForm,
    OrganizationForm,
)
from ..admin_views import (
    dashboard,
    panel_devices,
    panel_firmware,
    panel_memberships,
    panel_organizations,
    panel_ota,
    panel_profiles,
    panel_registrations,
)
from ..models import Device, Organization, OrganizationMembership, TelemetryRecord
from ..wagtail_hooks import register_iot_menu_item


class IoTDashboardTests(TestCase):
    def test_dashboard_exposes_operational_fleet_metrics(self):
        user = get_user_model().objects.create_superuser(
            username="fleet-admin", email="fleet@example.com", password="x"
        )
        org = Organization.objects.create(name="Factory")
        device = Device.objects.create(
            organization=org,
            name="Boiler sensor",
            last_seen_at=timezone.now(),
            reported_firmware_version="1.4.0",
            hardware_version="rev-b",
        )
        TelemetryRecord.objects.create(
            device=device,
            channel="telemetry",
            schema="boiler.v1",
            payload={"temperature_c": 82.5},
            device_timestamp=timezone.now(),
        )
        request = RequestFactory().get("/admin/iot/")
        request.user = user

        response = dashboard(request)
        context = response.context_data

        self.assertEqual(response.status_code, 200)
        self.assertEqual(context["active_device_count"], 1)
        self.assertEqual(context["online_count"], 1)
        self.assertEqual(context["online_percentage"], 100)
        self.assertEqual(context["telemetry_24h"], 1)
        self.assertEqual(context["recent_activity"][0]["schema"], "boiler.v1")
        self.assertEqual(context["devices"][0]["firmware_version"], "1.4.0")

    def test_iot_sidebar_is_a_single_menu_item(self):
        item = register_iot_menu_item()

        self.assertIsInstance(item, MenuItem)
        self.assertEqual(item.name, "iot-menu")

    def test_workspace_quick_create_forms_create_tenant_and_user_access(self):
        organization_form = OrganizationForm({"name": "North Plant", "is_active": True})
        self.assertTrue(organization_form.is_valid(), organization_form.errors)
        organization = organization_form.save()

        user_form = IoTUserMembershipForm(
            {
                "username": "plant-operator",
                "email": "operator@example.com",
                "organization": organization.pk,
                "role": "admin",
                "password1": "Rhamaa-test-pass-4831",
                "password2": "Rhamaa-test-pass-4831",
            }
        )
        self.assertTrue(user_form.is_valid(), user_form.errors)
        user = user_form.save()

        self.assertTrue(
            OrganizationMembership.objects.filter(
                user=user, organization=organization, role="admin"
            ).exists()
        )

        existing_user = get_user_model().objects.create_user(
            username="existing-operator", email="existing@example.com", password="x"
        )
        existing_form = ExistingUserMembershipForm(
            {
                "user": existing_user.pk,
                "organization": organization.pk,
                "role": "viewer",
            }
        )
        self.assertTrue(existing_form.is_valid(), existing_form.errors)
        existing_membership = existing_form.save()
        self.assertEqual(existing_membership.user, existing_user)
        self.assertEqual(existing_membership.role, "viewer")

        duplicate_form = ExistingUserMembershipForm(
            {
                "user": existing_user.pk,
                "organization": organization.pk,
                "role": "member",
            }
        )
        self.assertFalse(duplicate_form.is_valid())

    def test_all_workspace_panels_render_inside_the_iot_shell(self):
        user = get_user_model().objects.create_superuser(
            username="workspace-admin", email="admin@example.com", password="x"
        )
        request = RequestFactory().get("/admin/iot/")
        request.user = user

        legacy_response = panel_organizations(request)
        self.assertEqual(legacy_response.status_code, 302)
        self.assertIn("/memberships/", legacy_response.url)

        for view, has_create_modal in (
            (panel_memberships, True),
            (panel_profiles, True),
            (panel_devices, True),
            (panel_registrations, False),
            (panel_firmware, True),
            (panel_ota, False),
        ):
            response = view(request)
            response.render()
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "iot-subnav")
            content = response.content.decode()
            if view is panel_memberships:
                hero_marker = '<header class="iot-access-hero iot-command-hero'
            elif view is panel_devices:
                hero_marker = '<div class="iot-hero iot-command-hero"'
            else:
                hero_marker = '<div class="iot-hero'
            self.assertLess(content.index('<nav class="iot-subnav"'), content.index(hero_marker))
            if has_create_modal:
                self.assertIn("data-iot-modal-open", content)
                self.assertIn('class="iot-dialog', content)
            if view is panel_memberships:
                self.assertIn('class="iot-access-grid"', content)
                self.assertIn("Tambah organisasi", content)
                self.assertIn('data-iot-membership-panel="new"', content)
                self.assertIn('data-iot-membership-panel="existing"', content)
            if view in {panel_profiles, panel_devices, panel_registrations, panel_firmware, panel_ota}:
                device_hero_marker = '<div class="iot-hero iot-command-hero"' if view is panel_devices else '<div class="iot-hero'
                self.assertLess(
                    content.index('<nav class="iot-device-nav"'),
                    content.index(device_hero_marker),
                )
