"""Guards against a model silently losing its admin registration.

`django.contrib.admin.autodiscover()` only ever imports `deployments.admin` -- now a package
-- so a submodule that `deployments/admin/__init__.py` forgets to import never runs its
`@admin.register` calls, and the model just vanishes from the admin with nothing else
noticing. This test is the thing that would catch that.
"""

import pytest
from django.contrib import admin

from deployments.models import (
    BufferType,
    DataType,
    ErddapDataset,
    ErddapServer,
    MooringType,
    Platform,
    Program,
    StationType,
    SystemMessage,
    TimeSeries,
)


@pytest.mark.parametrize(
    "model",
    [
        Platform,
        TimeSeries,
        ErddapDataset,
        ErddapServer,
        SystemMessage,
        DataType,
        BufferType,
        Program,
        MooringType,
        StationType,
    ],
)
def test_model_is_registered_with_admin(model):
    assert model in admin.site._registry  # noqa: SLF001 - no public "is this registered?" API
