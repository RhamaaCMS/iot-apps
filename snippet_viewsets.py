"""Wagtail snippet registration isolated from domain models.

Until tenant-aware create/edit forms exist, raw snippet CRUD is superuser-only.
Tenant operators use scoped IoT panels and APIs.
"""

from django.core.exceptions import PermissionDenied
from wagtail.snippets.views.snippets import (
    CreateView,
    DeleteView,
    EditView,
    IndexView,
    SnippetViewSet,
)
from wagtail.snippets.views.chooser import (
    ChooseResultsView,
    ChooseView,
    SnippetChosenMultipleView,
    SnippetChosenView,
    SnippetChooserViewSet,
)

from .models import (
    Device,
    DeviceOTAJob,
    DeviceProfile,
    FirmwareVersion,
    Organization,
    OrganizationMembership,
)


class SuperuserRequiredMixin:
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class SuperuserIndexView(SuperuserRequiredMixin, IndexView):
    pass


class SuperuserCreateView(SuperuserRequiredMixin, CreateView):
    pass


class SuperuserEditView(SuperuserRequiredMixin, EditView):
    pass


class SuperuserDeleteView(SuperuserRequiredMixin, DeleteView):
    pass


class SuperuserChooseView(SuperuserRequiredMixin, ChooseView):
    pass


class SuperuserChooseResultsView(SuperuserRequiredMixin, ChooseResultsView):
    pass


class SuperuserChosenView(SuperuserRequiredMixin, SnippetChosenView):
    pass


class SuperuserChosenMultipleView(SuperuserRequiredMixin, SnippetChosenMultipleView):
    pass


class SuperuserSnippetChooserViewSet(SnippetChooserViewSet):
    choose_view_class = SuperuserChooseView
    choose_results_view_class = SuperuserChooseResultsView
    chosen_view_class = SuperuserChosenView
    chosen_multiple_view_class = SuperuserChosenMultipleView


class SuperuserSnippetViewSet(SnippetViewSet):
    index_view_class = SuperuserIndexView
    add_view_class = SuperuserCreateView
    edit_view_class = SuperuserEditView
    delete_view_class = SuperuserDeleteView
    copy_view_enabled = False
    inspect_view_enabled = False
    chooser_viewset_class = SuperuserSnippetChooserViewSet

    def get_queryset(self, request):
        if not request.user.is_superuser:
            return self.model.objects.none()
        return self.model.objects.all()


class OrganizationViewSet(SuperuserSnippetViewSet):
    model = Organization


class OrganizationMembershipViewSet(SuperuserSnippetViewSet):
    model = OrganizationMembership


class DeviceProfileViewSet(SuperuserSnippetViewSet):
    model = DeviceProfile


class DeviceViewSet(SuperuserSnippetViewSet):
    model = Device


class FirmwareVersionViewSet(SuperuserSnippetViewSet):
    model = FirmwareVersion


class DeviceOTAJobViewSet(SuperuserSnippetViewSet):
    model = DeviceOTAJob


IOT_SNIPPET_VIEWSETS = (
    OrganizationViewSet,
    OrganizationMembershipViewSet,
    DeviceProfileViewSet,
    DeviceViewSet,
    FirmwareVersionViewSet,
    DeviceOTAJobViewSet,
)
