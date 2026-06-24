from backend.core.config import PROJECT_ROOT


def test_project_root_points_to_launcher_directory():
    assert (PROJECT_ROOT / "app.py").is_file()
    assert (PROJECT_ROOT / "backend").is_dir()
