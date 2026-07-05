from __future__ import annotations

from pydantic import BaseModel, Field


class MedicalSchema(BaseModel):
    doc_type: str = Field(default="medical")
    patient_name: str = ""
    patient_age: str = ""
    patient_sex: str = ""
    certificate_date: str = ""
    doctor_name: str = ""
    doctor_registration_no: str = ""
    hospital_name: str = ""
    diagnosis: str = ""
    medical_statement: str = ""
    admission_date: str = ""
    discharge_date: str = ""
    country_name: str = ""
