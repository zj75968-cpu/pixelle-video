from __future__ import annotations

from pathlib import Path


def test_run_profile_values_match_design() -> None:
    from pixelle_video.app.profiles import RunProfile

    assert RunProfile.LOCAL_UI == "local_ui"
    assert RunProfile.API_SERVER == "api_server"
    assert RunProfile.WORKER == "worker"
    assert RunProfile.CLI == "cli"
    assert RunProfile.DEV == "dev"
    assert RunProfile.TEST == "test"
    assert [profile.value for profile in RunProfile] == [
        "local_ui",
        "api_server",
        "worker",
        "cli",
        "dev",
        "test",
    ]


def test_run_profile_coerces_strings_and_instances() -> None:
    from pixelle_video.app.profiles import RunProfile

    assert RunProfile.coerce("LOCAL_UI") is RunProfile.LOCAL_UI
    assert RunProfile.coerce("api_server") is RunProfile.API_SERVER
    assert RunProfile.coerce(RunProfile.WORKER) is RunProfile.WORKER


def test_app_context_carries_baseline_fields() -> None:
    from pixelle_video.app.context import AppContext
    from pixelle_video.app.profiles import RunProfile

    project_root = Path("/project")
    data_dir = Path("/project/data")
    output_dir = Path("/project/output")

    context = AppContext(
        profile=RunProfile.LOCAL_UI,
        project_root=project_root,
        data_dir=data_dir,
        output_dir=output_dir,
    )

    assert context.profile is RunProfile.LOCAL_UI
    assert context.project_root == project_root
    assert context.data_dir == data_dir
    assert context.output_dir == output_dir
    assert context.user == "default"


def test_app_package_exports_baseline_types() -> None:
    from pixelle_video.app import AppContext, RunProfile
    from pixelle_video.app.context import AppContext as ContextModuleAppContext
    from pixelle_video.app.profiles import RunProfile as ProfilesModuleRunProfile

    assert AppContext is ContextModuleAppContext
    assert RunProfile is ProfilesModuleRunProfile


def test_api_lifecycle_uses_canonical_run_profile() -> None:
    from api.lifecycle import RunProfile as LifecycleRunProfile
    from pixelle_video.app.profiles import RunProfile

    assert LifecycleRunProfile is RunProfile
