from .BaseController import BaseController
from .ProjectController import ProjectController
from fastapi import UploadFile
from models import ResponseSignal
import re
import os

class DataController(BaseController):
    
    def __init__(self):
        super().__init__()
        self.size_scale = 1048576 # convert MB to bytes

    def validate_uploaded_file(self, file: UploadFile):

        # Allow PDF, TXT, and common image types (for OCR).
        allowed_exts = {".pdf", ".txt", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif"}
        fname = (file.filename or "").lower()
        ext_ok = any(fname.endswith(ext) for ext in allowed_exts)

        allowed_types = set(getattr(self.app_settings, "FILE_ALLOWED_TYPES", []) or [])
        type_ok = (
            file.content_type in allowed_types
            or file.content_type in (
                "application/pdf",
                "application/x-pdf",
                "text/plain",
                "image/png",
                "image/jpeg",
                "image/tiff",
                "image/bmp",
                "image/gif",
            )
        )

        if not ext_ok and not type_ok:
            return False, ResponseSignal.FILE_TYPE_NOT_SUPPORTED.value

        if file.size > self.app_settings.FILE_MAX_SIZE * self.size_scale:
            return False, ResponseSignal.FILE_SIZE_EXCEEDED.value

        return True, ResponseSignal.FILE_VALIDATED_SUCCESS.value

    def generate_unique_filepath(self, orig_file_name: str, project_id: str):

        random_key = self.generate_random_string()
        project_path = ProjectController().get_project_path(project_id=project_id)

        cleaned_file_name = self.get_clean_file_name(
            orig_file_name=orig_file_name
        )

        new_file_path = os.path.join(
            project_path,
            random_key + "_" + cleaned_file_name
        )

        while os.path.exists(new_file_path):
            random_key = self.generate_random_string()
            new_file_path = os.path.join(
                project_path,
                random_key + "_" + cleaned_file_name
            )

        return new_file_path, random_key + "_" + cleaned_file_name

    def get_clean_file_name(self, orig_file_name: str):

        # remove any special characters, except underscore and .
        cleaned_file_name = re.sub(r'[^\w.]', '', orig_file_name.strip())

        # replace spaces with underscore
        cleaned_file_name = cleaned_file_name.replace(" ", "_")

        return cleaned_file_name
