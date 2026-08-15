"""Checks over the generated endpoint hints.

apps_generated.py and hints_generated.pyi come from
scripts/generate_endpoints.py. These tests make sure the two stay
consistent with each other and with the runtime classes, so a bad
regeneration fails CI instead of silently degrading autocomplete.
"""

import ast
import re
from pathlib import Path

from conftest import BASE

from aiopynautobot import apps_generated
from aiopynautobot.app import SPECIAL_ENDPOINTS, App
from aiopynautobot.apps_generated import APP_CLASSES
from aiopynautobot.models import ENDPOINT_MODELS

SRC = Path(__file__).resolve().parent.parent / "src" / "aiopynautobot"
STUB = SRC / "hints_generated.pyi"


def stub_class_names() -> set[str]:
    """Class names defined in the stub, parsed rather than imported.

    hints_generated.pyi is stub-only: it is never importable at runtime,
    so this reads it as source.
    """
    tree = ast.parse(STUB.read_text(encoding="utf-8"))
    return {n.name for n in tree.body if isinstance(n, ast.ClassDef)}


def stub_bases() -> dict[str, list[str]]:
    tree = ast.parse(STUB.read_text(encoding="utf-8"))
    return {
        n.name: [b.id for b in n.bases if isinstance(b, ast.Name)]
        for n in tree.body
        if isinstance(n, ast.ClassDef)
    }


def test_every_annotation_resolves_to_a_stub_class():
    names = stub_class_names()
    missing = []
    for app_class in APP_CLASSES.values():
        for attr, annotation in app_class.__annotations__.items():
            # Annotations are strings: "hints.DcimDevicesEndpoint".
            target = str(annotation).split(".")[-1]
            if target not in names:
                missing.append(f"{app_class.__name__}.{attr} -> {target}")
    assert not missing


def test_every_app_on_the_client_has_a_generated_class(nb):
    for name, app_class in APP_CLASSES.items():
        attr = name.replace("-", "_")
        app = getattr(nb, attr, None)
        assert app is not None, f"Api has no .{attr}"
        assert isinstance(app, app_class)
        assert app.name == name


def test_generated_classes_subclass_app():
    for app_class in APP_CLASSES.values():
        assert issubclass(app_class, App)


def test_annotations_create_no_runtime_attributes(nb):
    """The hints are static-only; App.__getattr__ is the real mechanism."""
    assert "devices" not in type(nb.dcim).__dict__
    assert nb.dcim.devices.url == f"{BASE}/api/dcim/devices/"


def test_unlisted_endpoints_still_work(nb):
    """An endpoint missing from the schema must not be blocked at runtime."""
    assert nb.dcim.not_a_real_endpoint.url == f"{BASE}/api/dcim/not-a-real-endpoint/"


def test_special_endpoints_keep_their_base_class_in_the_stub():
    """extras.jobs is a JobsEndpoint at runtime; the stub must agree,
    otherwise run() vanishes from the hints."""
    bases = stub_bases()
    assert bases["ExtrasJobsEndpoint"] == ["JobsEndpoint"]
    assert bases["ExtrasGraphqlQueriesEndpoint"] == ["GraphqlEndpoint"]
    # And the runtime side agrees on which names are special.
    assert set(SPECIAL_ENDPOINTS) == {"jobs", "graphql_queries"}


def test_model_backed_endpoints_return_their_subclass():
    """An endpoint mapped in ENDPOINT_MODELS should say so in the hints."""
    source = STUB.read_text(encoding="utf-8")
    checked = 0
    for key, record_class in ENDPOINT_MODELS.items():
        app, slug = key.split("/")
        if app == "plugins":
            continue
        cls = "".join(p.capitalize() for p in app.split("-"))
        cls += "".join(p.capitalize() for p in slug.replace("-", "_").split("_"))
        if f"class {cls}Endpoint(" not in source:
            continue  # endpoint absent from this Nautobot release
        block = source.split(f"class {cls}Endpoint(", 1)[1].split("\nclass ", 1)[0]
        assert record_class.__name__ in block, key
        checked += 1
    assert checked > 20, f"only {checked} model endpoints verified"


def test_stub_is_not_importable_at_runtime():
    """It is a .pyi; nothing may import it, which is why pyright's
    reportMissingModuleSource is disabled in pyproject.toml."""
    assert not (SRC / "hints_generated.py").exists()


def test_generated_files_record_their_source():
    header = (SRC / "apps_generated.py").read_text(encoding="utf-8")[:1200]
    assert "do not edit by hand" in header
    assert re.search(r"Source: https?://\S+", header)


def test_no_lookup_or_custom_field_params_in_typed_dicts():
    """Those are excluded at generation; the **kwargs: Any overloads keep
    them legal at the call site."""
    source = STUB.read_text(encoding="utf-8")
    fields = re.findall(r"^    (\w+): Any$", source, flags=re.MULTILINE)
    assert fields
    assert not [f for f in fields if "__" in f or f.startswith("cf_")]


def test_typed_dicts_are_total_false():
    """Every filter/field key must be optional."""
    source = STUB.read_text(encoding="utf-8")
    for match in re.finditer(r"^class (\w+)\(TypedDict(.*?)\):$", source, re.MULTILINE):
        assert "total=False" in match.group(2), match.group(1)


def test_app_classes_covers_every_generated_class():
    """APP_CLASSES must not drift from the classes in the module."""
    defined = {
        name
        for name, obj in vars(apps_generated).items()
        if isinstance(obj, type) and obj.__module__ == apps_generated.__name__
    }
    assert defined == {c.__name__ for c in APP_CLASSES.values()}
