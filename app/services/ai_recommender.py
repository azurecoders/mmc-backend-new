import json
import logging
import re
from typing import Any, Dict, List, Optional
import httpx
from app.core.config import settings
from app.models.department import Department
from app.models.doctor import DoctorProfile
from app.schemas.appointment import DoctorRecommendationItem, AIRecommendDoctorsResponse
from app.schemas.doctor import DoctorProfileResponse

logger = logging.getLogger(__name__)

DEPARTMENT_KEYWORD_MAP = {
    "CARDIOLOGY": ["chest", "heart", "breath", "palpitation", "cardiac", "pulse", "blood pressure", "hypertension", "angina"],
    "DERMATOLOGY": ["skin", "rash", "itching", "acne", "allergy", "hair", "eczema", "mole", "dermatitis"],
    "NEUROLOGY": ["headache", "migraine", "dizzy", "numbness", "seizure", "paralysis", "tremor", "nerve", "stroke", "concussion"],
    "ORTHOPEDICS": ["bone", "joint", "fracture", "knee", "spine", "back pain", "shoulder", "ligament", "sprain", "arthritis"],
    "PEDIATRICS": ["child", "baby", "infant", "kid", "vaccination", "pediatric", "teething"],
    "ENT": ["ear", "nose", "throat", "hearing", "tonsil", "sinus", "vertigo", "nasal"],
    "GENERAL_MEDICINE": ["fever", "cough", "cold", "flu", "weakness", "fatigue", "vomiting", "stomach", "diarrhea", "infection"],
}

class AIRecommenderService:
    @staticmethod
    async def recommend_doctors(
        symptoms: str,
        duration: Optional[str],
        severity: Optional[str],
        departments: List[Department],
        doctors: List[DoctorProfile],
    ) -> AIRecommendDoctorsResponse:
        """
        Recommends best department and doctors using Google AI Studio 'gemma-4-31b-it'
        with fallback to keyword/clinical heuristic analysis if offline or unconfigured.
        """
        api_key = settings.GOOGLE_AI_API_KEY
        
        # If API key is available, attempt LLM call
        if api_key:
            try:
                return await AIRecommenderService._call_gemma_api(
                    api_key=api_key,
                    symptoms=symptoms,
                    duration=duration,
                    severity=severity,
                    departments=departments,
                    doctors=doctors,
                )
            except Exception as e:
                logger.warning(f"Google AI Studio Gemma API error: {e}. Falling back to clinical heuristic.")

        # Fallback heuristic
        return AIRecommenderService._clinical_fallback(
            symptoms=symptoms,
            duration=duration,
            severity=severity,
            departments=departments,
            doctors=doctors,
        )

    @staticmethod
    async def _call_gemma_api(
        api_key: str,
        symptoms: str,
        duration: Optional[str],
        severity: Optional[str],
        departments: List[Department],
        doctors: List[DoctorProfile],
    ) -> AIRecommendDoctorsResponse:
        departments_summary = [
            {"code": d.code, "name": d.name, "description": d.description}
            for d in departments if d.is_active
        ]
        doctors_summary = [
            {
                "doctor_id": str(doc.id),
                "name": doc.user.full_name if doc.user else "Doctor",
                "department_code": doc.department.code if doc.department else "GENERAL_MEDICINE",
                "department_name": doc.department.name if doc.department else "General Medicine",
                "specialization": doc.specialization,
                "qualifications": doc.qualifications,
                "experience_years": doc.experience_years,
                "consultation_fee": float(doc.consultation_fee),
                "room_number": doc.room_number,
            }
            for doc in doctors if doc.is_available
        ]

        system_prompt = (
            "You are an expert Clinical Triage AI Assistant in a Hospital Management System. "
            "A patient has submitted symptoms for booking an appointment. "
            "Your task is to analyze the symptoms, determine the most appropriate hospital department, "
            "assess the urgency level, and select the best matching doctor(s) from the hospital's available staff.\n\n"
            "Return strictly valid JSON with this exact schema:\n"
            "{\n"
            '  "recommended_department_code": "DEPARTMENT_CODE",\n'
            '  "urgency_level": "ROUTINE" | "URGENT" | "EMERGENCY",\n'
            '  "clinical_assessment": "Brief 1-2 sentence medical triage summary of symptoms",\n'
            '  "recommendations": [\n'
            '    {\n'
            '      "doctor_id": "UUID_STRING",\n'
            '      "match_score": 0.95,\n'
            '      "reason": "Specific reason why this doctor suits the patient case"\n'
            '    }\n'
            '  ]\n'
            "}"
        )

        user_content = (
            f"Patient Symptoms: {symptoms}\n"
            f"Duration: {duration or 'Not specified'}\n"
            f"Reported Severity: {severity or 'Moderate'}\n\n"
            f"Available Hospital Departments:\n{json.dumps(departments_summary, indent=2)}\n\n"
            f"Available Doctors:\n{json.dumps(doctors_summary, indent=2)}\n"
        )

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"{system_prompt}\n\n{user_content}"}],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 1000,
            },
        }

        # Try models in order: configured model -> gemma-4-26b-a4b-it -> gemini-2.5-flash
        candidate_models = [settings.AI_RECOMMENDER_MODEL, "gemma-4-26b-a4b-it", "gemini-2.5-flash"]
        # Deduplicate while preserving order
        candidate_models = list(dict.fromkeys(candidate_models))

        last_error = None
        parsed = None

        async with httpx.AsyncClient(timeout=25.0) as client:
            for model_name in candidate_models:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                try:
                    resp = await client.post(url, json=payload)
                    if resp.status_code != 200:
                        logger.warning(f"AI API model {model_name} returned status {resp.status_code}: {resp.text[:120]}")
                        continue
                    
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if not candidates:
                        continue
                    parts = candidates[0].get("content", {}).get("parts", [])
                    # Extract non-thought text (handles Gemma CoT thinking mode)
                    non_thought = [p["text"] for p in parts if not p.get("thought") and "text" in p]
                    raw_text = non_thought[-1] if non_thought else (parts[-1].get("text", "") if parts else "")

                    clean_json = raw_text.strip()
                    if "```" in clean_json:
                        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_json)
                        if match:
                            clean_json = match.group(1).strip()

                    parsed = json.loads(clean_json)
                    logger.info(f"Successfully received recommendation from model {model_name}")
                    break
                except Exception as err:
                    logger.warning(f"Model {model_name} failed: {err}")
                    last_error = err

        if not parsed:
            raise RuntimeError(f"All AI candidate models failed. Last error: {last_error}")

        # Map doctor IDs to full DoctorProfileResponse
        doctors_map = {str(d.id): d for d in doctors}
        rec_items: List[DoctorRecommendationItem] = []
        
        for item in parsed.get("recommendations", []):
            doc_id_str = item.get("doctor_id")
            if doc_id_str in doctors_map:
                doc = doctors_map[doc_id_str]
                rec_items.append(
                    DoctorRecommendationItem(
                        doctor=DoctorProfileResponse.model_validate(doc),
                        match_score=float(item.get("match_score", 0.9)),
                        match_reason=item.get("reason", "Specialist match for symptoms"),
                    )
                )

        # If no valid doctor IDs matched from response, fallback to department doctors
        if not rec_items:
            dept_code = parsed.get("recommended_department_code", "GENERAL_MEDICINE")
            for doc in doctors:
                if doc.department and doc.department.code == dept_code:
                    rec_items.append(
                        DoctorRecommendationItem(
                            doctor=DoctorProfileResponse.model_validate(doc),
                            match_score=0.85,
                            match_reason=f"Specialist in {doc.department.name}",
                        )
                    )

        return AIRecommendDoctorsResponse(
            recommended_department=parsed.get("recommended_department_code", "GENERAL_MEDICINE"),
            urgency_level=parsed.get("urgency_level", "ROUTINE"),
            clinical_assessment=parsed.get("clinical_assessment", "Symptom evaluation completed."),
            recommended_doctors=rec_items,
            fallback_used=False,
        )

    @staticmethod
    def _clinical_fallback(
        symptoms: str,
        duration: Optional[str],
        severity: Optional[str],
        departments: List[Department],
        doctors: List[DoctorProfile],
    ) -> AIRecommendDoctorsResponse:
        """
        Heuristic clinical matcher used when LLM API is unavailable or offline.
        """
        text = symptoms.lower()
        matched_dept_code = "GENERAL_MEDICINE"
        highest_keyword_hits = 0

        for dept_code, keywords in DEPARTMENT_KEYWORD_MAP.items():
            hits = sum(1 for kw in keywords if kw in text)
            if hits > highest_keyword_hits:
                highest_keyword_hits = hits
                matched_dept_code = dept_code

        # Urgency assessment
        urgency = "ROUTINE"
        if severity == "SEVERE" or any(kw in text for kw in ["severe", "unbearable", "bleeding", "collapse", "chest pain"]):
            urgency = "URGENT"

        # Find matching doctors
        rec_items: List[DoctorRecommendationItem] = []
        dept_doctors = [
            d for d in doctors
            if d.is_available and d.department and d.department.code == matched_dept_code
        ]
        
        # Sort by experience
        dept_doctors.sort(key=lambda d: d.experience_years, reverse=True)

        for doc in dept_doctors:
            rec_items.append(
                DoctorRecommendationItem(
                    doctor=DoctorProfileResponse.model_validate(doc),
                    match_score=0.92,
                    match_reason=f"Qualified {doc.specialization} with {doc.experience_years} years experience in {doc.department.name}.",
                )
            )

        # If no doctor in that department, include General Medicine doctors
        if not rec_items:
            gen_doctors = [
                d for d in doctors
                if d.is_available and d.department and d.department.code == "GENERAL_MEDICINE"
            ]
            for doc in gen_doctors:
                rec_items.append(
                    DoctorRecommendationItem(
                        doctor=DoctorProfileResponse.model_validate(doc),
                        match_score=0.80,
                        match_reason="General Physician available for primary clinical assessment.",
                    )
                )

        dept_obj = next((d for d in departments if d.code == matched_dept_code), None)
        dept_display_name = dept_obj.name if dept_obj else matched_dept_code

        assessment = (
            f"Based on reported symptoms '{symptoms}', primary evaluation by {dept_display_name} "
            f"is recommended with {urgency.lower()} priority."
        )

        return AIRecommendDoctorsResponse(
            recommended_department=matched_dept_code,
            urgency_level=urgency,
            clinical_assessment=assessment,
            recommended_doctors=rec_items,
            fallback_used=True,
        )

ai_recommender_service = AIRecommenderService()
