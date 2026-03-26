from .BaseController import BaseController
from fastapi import UploadFile
from models import ResponseSignal
import os

class ProjectController(BaseController):
    
    def __init__(self):
        super().__init__()

    def get_project_path(self, project_id: str):
        project_str = str(project_id).strip()
        if not project_str:
            raise ValueError("Invalid project_id")
        if os.sep in project_str or (os.altsep and os.altsep in project_str):
            raise ValueError("Invalid project_id")

        base_dir = os.path.abspath(os.path.normpath(self.files_dir))
        project_dir = os.path.abspath(
            os.path.normpath(os.path.join(base_dir, project_str))
        )

        if os.path.commonpath([base_dir, project_dir]) != base_dir:
            raise ValueError("Invalid project path")

        if not os.path.exists(project_dir):
            os.makedirs(project_dir, exist_ok=True)

        return project_dir

    def resolve_project_file_path(self, project_id: str, file_name: str) -> str:
        project_dir = self.get_project_path(project_id=project_id)
        safe_name = os.path.basename(str(file_name or "").strip())
        if not safe_name or safe_name in {".", ".."}:
            raise ValueError("Invalid file name")

        file_path = os.path.abspath(
            os.path.normpath(os.path.join(project_dir, safe_name))
        )
        if os.path.commonpath([project_dir, file_path]) != project_dir:
            raise ValueError("Invalid file path")

        return file_path

    
