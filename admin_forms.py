from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import (
    Device,
    DeviceProfile,
    FirmwareVersion,
    MemberRole,
    Organization,
    OrganizationMembership,
)

UserModel = get_user_model()


class IoTUserChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, user):
        email = getattr(user, "email", "") or "tanpa email"
        return f"{user.get_username()} — {email}"


class IoTAdminFormMixin:
    """Small, dependency-free form styling for the IoT workspace dialogs."""

    def _style_fields(self):
        for field in self.fields.values():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css} iot-form-control".strip()


class OrganizationForm(IoTAdminFormMixin, forms.ModelForm):
    class Meta:
        model = Organization
        fields = ("name", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class IoTUserMembershipForm(IoTAdminFormMixin, UserCreationForm):
    email = forms.EmailField(required=True, label="Email")
    organization = forms.ModelChoiceField(
        queryset=Organization.objects.filter(is_active=True).order_by("name"),
        label="Organisasi",
    )
    role = forms.ChoiceField(
        choices=MemberRole.choices, initial=MemberRole.MEMBER, label="Peran"
    )

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            OrganizationMembership.objects.create(
                user=user,
                organization=self.cleaned_data["organization"],
                role=self.cleaned_data["role"],
            )
        return user


class ExistingUserMembershipForm(IoTAdminFormMixin, forms.ModelForm):
    user = IoTUserChoiceField(
        queryset=UserModel.objects.filter(is_active=True).order_by(
            UserModel.USERNAME_FIELD
        ),
        label="User terdaftar",
        help_text="Pilih akun Django/Wagtail yang sudah tersedia.",
    )

    class Meta:
        model = OrganizationMembership
        fields = ("user", "organization", "role")
        labels = {"organization": "Organisasi", "role": "Peran"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["organization"].queryset = Organization.objects.filter(
            is_active=True
        ).order_by("name")
        self._style_fields()


class DeviceProfileForm(IoTAdminFormMixin, forms.ModelForm):
    class Meta:
        model = DeviceProfile
        fields = (
            "organization",
            "name",
            "slug",
            "product_code",
            "allowed_schemas",
            "heartbeat_interval_seconds",
            "is_active",
        )
        widgets = {"allowed_schemas": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class DeviceForm(IoTAdminFormMixin, forms.ModelForm):
    class Meta:
        model = Device
        fields = (
            "organization",
            "profile",
            "name",
            "device_id",
            "is_active",
            "topic_prefix",
            "firmware_product",
            "hardware_version",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class FirmwareVersionForm(IoTAdminFormMixin, forms.ModelForm):
    class Meta:
        model = FirmwareVersion
        fields = (
            "profile",
            "version",
            "file",
            "is_active",
            "is_mandatory",
            "min_hardware_version",
            "max_hardware_version",
            "release_notes",
        )
        widgets = {"release_notes": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["profile"].required = True
        self._style_fields()
