from __future__ import annotations

from pydantic import BaseModel, Field


class BirthSchema(BaseModel):
    doc_type: str = Field(default="birth")
    register_no: str = ""
    serial_no: str = ""
    place: str = ""
    tehsil: str = ""
    district: str = ""
    year: str = ""
    child_name: str = ""
    sex: str = ""
    father_name: str = ""
    grandfather_name: str = ""
    mother_name: str = ""
    birth_date: str = ""
    birth_place: str = ""
    reg_date: str = ""
    address: str = ""
    permanent_address: str = ""
    issue_date: str = ""
    print_date: str = ""
    signature_name: str = ""
    signature_date: str = ""
    location: str = ""
    designation: str = ""
    reference_no: str = ""
    apostille_sign: str = ""
    signed_by: str = ""
    apostille_date: str = ""
    stamp_no: str = ""

