"""
Resolved Wagtail Snippet list/add/edit URLs for `iot` models.
"""

from __future__ import annotations

from django.urls import NoReverseMatch, reverse


def _viewset_name(model_meta_name: str) -> str:
    return f"wagtailsnippets_iot_{model_meta_name}"


def snippet_list_url(model_meta_name: str) -> str:
    return reverse(f"{_viewset_name(model_meta_name)}:list")


def snippet_add_url(model_meta_name: str) -> str:
    return reverse(f"{_viewset_name(model_meta_name)}:add")


def snippet_edit_url(model_meta_name: str, pk: int) -> str:
    return reverse(f"{_viewset_name(model_meta_name)}:edit", args=[pk])


def all_snippet_links(user=None) -> dict:
    """
    For templates: list, add, and (optional) discover views.
    """
    if user is not None and not user.is_superuser:
        return {}
    out: dict = {}
    for name in (
        "organization",
        "organizationmembership",
        "deviceprofile",
        "device",
        "firmwareversion",
        "deviceotajob",
    ):
        try:
            out[name] = {
                "list": snippet_list_url(name),
                "add": snippet_add_url(name),
            }
        except NoReverseMatch:  # pragma: no cover
            out[name] = {"list": "#", "add": "#"}
    return out
