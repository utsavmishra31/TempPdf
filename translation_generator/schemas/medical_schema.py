from __future__ import annotations

from pydantic import BaseModel, Field


class MedicalSchema(BaseModel):
    doc_type: str = Field(default="medical")
    name: str = ""
    relation_text: str = ""
    relation_text_es: str = ""
    father_name: str = ""
    passport_no: str = ""
    certificate_date: str = ""
    reference_no: str = ""
    sign_name: str = ""
    signed_by: str = ""
    apostille_date: str = ""
    stamp_no: str = ""
