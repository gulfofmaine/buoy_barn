from django import forms

from .models import ErddapServer, Platform


class ErddapImportForm(forms.Form):
    """Which ERDDAP dataset to import, and which platform to import it to"""

    server = forms.ModelChoiceField(queryset=ErddapServer.objects.order_by("name"))
    dataset_id = forms.CharField(
        label="Dataset ID",
        max_length=256,
        help_text="As ERDDAP knows it. EX: 'M01_sbe37_all'",
    )
    constraints = forms.JSONField(
        required=False,
        help_text=(
            'Extra ERDDAP constraints, for example {"depth=": 1.0} or '
            '{"station=": "44027"}. QC constraints are added from the metadata.'
        ),
    )
    platform = forms.ModelChoiceField(
        queryset=Platform.objects.order_by("name"),
        required=False,
        help_text="Import the dataset to an existing platform...",
    )
    new_platform_name = forms.CharField(
        label="New platform slug/station_id",
        max_length=50,
        required=False,
        help_text="...or create a new platform",
    )

    def clean_constraints(self):
        constraints = self.cleaned_data.get("constraints")
        if constraints in (None, ""):
            return {}
        if not isinstance(constraints, dict):
            raise forms.ValidationError('Constraints must be a JSON object, like {"depth=": 1.0}')
        return constraints

    def clean(self):
        cleaned = super().clean()
        platform = cleaned.get("platform")
        name = (cleaned.get("new_platform_name") or "").strip()
        cleaned["new_platform_name"] = name

        if platform and name:
            raise forms.ValidationError("Choose an existing platform or a new platform name, not both")
        if not platform and not name:
            raise forms.ValidationError("Choose an existing platform or enter a new platform name")
        if name and Platform.objects.filter(name=name).exists():
            self.add_error(
                "new_platform_name",
                f"A platform named {name!r} already exists, choose it as the existing platform",
            )
        return cleaned
