"""Tenant query scoping for IoT admin and APIs."""

from .models import MemberRole, OrganizationMembership


def organization_ids_for_user(user):
    if user.is_superuser:
        return None
    return OrganizationMembership.objects.filter(user=user).values_list("organization_id", flat=True)


def manageable_organization_ids_for_user(user):
    if user.is_superuser:
        return None
    return OrganizationMembership.objects.filter(
        user=user, role=MemberRole.ADMIN
    ).values_list("organization_id", flat=True)


def scope_manageable_devices(queryset, user):
    ids = manageable_organization_ids_for_user(user)
    return queryset if ids is None else queryset.filter(organization_id__in=ids)


def scope_manageable_ota_jobs(queryset, user):
    ids = manageable_organization_ids_for_user(user)
    return queryset if ids is None else queryset.filter(device__organization_id__in=ids)


def scope_organizations(queryset, user):
    ids = organization_ids_for_user(user)
    return queryset if ids is None else queryset.filter(pk__in=ids)


def scope_devices(queryset, user):
    ids = organization_ids_for_user(user)
    return queryset if ids is None else queryset.filter(organization_id__in=ids)


def scope_memberships(queryset, user):
    ids = organization_ids_for_user(user)
    return queryset if ids is None else queryset.filter(organization_id__in=ids)


def scope_ota_jobs(queryset, user):
    ids = organization_ids_for_user(user)
    return queryset if ids is None else queryset.filter(device__organization_id__in=ids)
