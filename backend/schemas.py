"""
Structured clinical data schema.

This is the contract between the LLM extraction step and the frontend.
Each field group maps directly to one panel in the "AI Medical Summary" UI.
Using Pydantic gives us two things:
  1. A JSON schema we can hand to the LLM as an explicit target shape.
  2. Runtime validation of whatever JSON the LLM returns, so a malformed
     response fails loudly in the backend instead of silently breaking
     the frontend renderer.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class PatientDetails(BaseModel):
    name: Optional[str] = Field(None, description="Patient's name, if stated")
    age: Optional[str] = None
    sex: Optional[str] = None
    identifiers: List[str] = Field(
        default_factory=list,
        description="Any other identifiers mentioned (ID numbers, referral source, etc.)",
    )


class HistoryOfPresentIllness(BaseModel):
    onset: Optional[str] = None
    duration: Optional[str] = None
    progression: Optional[str] = None
    aggravating_factors: List[str] = Field(default_factory=list)
    relieving_factors: List[str] = Field(default_factory=list)


class Symptoms(BaseModel):
    positive: List[str] = Field(
        default_factory=list, description="Symptoms the patient reports having"
    )
    negative: List[str] = Field(
        default_factory=list,
        description="Symptoms explicitly denied by the patient (pertinent negatives)",
    )


class MedicationHistory(BaseModel):
    current_medications: List[str] = Field(default_factory=list)
    adherence: Optional[str] = None
    allergies: List[str] = Field(default_factory=list)


class ClinicalObservations(BaseModel):
    vitals: List[str] = Field(default_factory=list)
    examination_findings: List[str] = Field(default_factory=list)


class Plan(BaseModel):
    investigations: List[str] = Field(default_factory=list)
    prescriptions: List[str] = Field(default_factory=list)
    advice: List[str] = Field(default_factory=list)
    follow_up: Optional[str] = None


class ClinicalSummary(BaseModel):
    """Top-level object returned by the LLM extraction step."""

    patient_details: PatientDetails = Field(default_factory=PatientDetails)
    chief_complaint: Optional[str] = None
    history_of_present_illness: HistoryOfPresentIllness = Field(
        default_factory=HistoryOfPresentIllness
    )
    symptoms: Symptoms = Field(default_factory=Symptoms)
    past_medical_history: List[str] = Field(default_factory=list)
    medication_history: MedicationHistory = Field(default_factory=MedicationHistory)
    clinical_observations: ClinicalObservations = Field(
        default_factory=ClinicalObservations
    )
    assessment: List[str] = Field(
        default_factory=list, description="Provisional diagnosis / differentials"
    )
    plan: Plan = Field(default_factory=Plan)
    narrative_summary: str = Field(
        "", description="2-4 sentence prose summary suitable for a medical record"
    )
