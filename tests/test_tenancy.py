from django.contrib.auth import get_user_model
from django.test import TestCase

from ..access import scope_devices
from ..models import Device, Organization, OrganizationMembership


class TenantScopeTests(TestCase):
    def test_member_only_sees_own_organization_devices(self):
        user = get_user_model().objects.create_user(username="operator", password="x")
        org_a = Organization.objects.create(name="A")
        org_b = Organization.objects.create(name="B")
        OrganizationMembership.objects.create(user=user, organization=org_a)
        device_a = Device.objects.create(organization=org_a, name="A1")
        Device.objects.create(organization=org_b, name="B1")
        self.assertQuerySetEqual(scope_devices(Device.objects.all(), user), [device_a])
