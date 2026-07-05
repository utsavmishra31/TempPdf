from __future__ import annotations

from pydantic import BaseModel, Field


class MarriageSchema(BaseModel):
    doc_type: str = Field(default="marriage")
    husband_name: str = ""
    wife_name: str = ""
    marriage_date: str = ""
    marriage_place: str = ""
    registration_no: str = ""
    registration_date: str = ""
    husband_father_name: str = ""
    wife_father_name: str = ""
    issuing_authority: str = ""
    certificate_date: str = ""
    country_name: str = ""
