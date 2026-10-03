from datetime import datetime, timezone
import json
import logging
import uuid
from typing import Any, Dict, List, Optional
from openai import AsyncOpenAI

from app.core.config import settings
from app.models.consultation import Consultation
from app.schemas.consultation import (
    MedicineExplanationItem,
    PrescriptionExplanationResponse,
)

logger = logging.getLogger(__name__)

# Common clinical medicine drug classification guide for intelligent fallback
DRUG_REFERENCE_DATABASE: Dict[str, Dict[str, str]] = {
    "amoxicillin": {
        "purpose": "A broad-spectrum penicillin antibiotic that fights bacterial infections by stopping bacterial cell wall growth.",
        "how_to_take": "Take at evenly spaced intervals with a full glass of water. Complete the entire prescribed duration even if you feel better.",
        "precautions_and_side_effects": "Common side effects include mild nausea or diarrhea. Seek urgent care if you develop hives, rash, or breathing difficulty.",
        "food_interaction": "Can be taken with or without food. Taking with a light meal or yogurt helps prevent stomach upset.",
    },
    "azithromycin": {
        "purpose": "A macrolide antibiotic used to treat respiratory infections, bronchitis, and throat infections.",
        "how_to_take": "Take once daily at the same time each day as prescribed.",
        "precautions_and_side_effects": "May cause mild stomach cramping or loose stools. Report severe dizziness or heart palpitations.",
        "food_interaction": "Best taken 1 hour before or 2 hours after meals with water.",
    },
    "paracetamol": {
        "purpose": "An analgesic and antipyretic medicine that relieves pain and reduces body temperature during fever.",
        "how_to_take": "Take as directed after food. Do not exceed the maximum daily allowance (4,000 mg in 24 hours).",
        "precautions_and_side_effects": "Generally well-tolerated. Avoid combining with other paracetamol/acetaminophen-containing cold medicines.",
        "food_interaction": "Avoid heavy alcohol consumption while taking this medication to protect your liver.",
    },
    "ibuprofen": {
        "purpose": "A non-steroidal anti-inflammatory drug (NSAID) that reduces inflammation, swelling, fever, and acute pain.",
        "how_to_take": "Always take with food or milk to protect your stomach lining. Drink plenty of fluids.",
        "precautions_and_side_effects": "May cause heartburn or stomach ache. Avoid if you have active stomach ulcers or severe kidney issues.",
        "food_interaction": "Take immediately after meals or with a glass of milk.",
    },
    "atorvastatin": {
        "purpose": "A statin cholesterol-lowering medication that protects cardiovascular health and prevents arterial plaque buildup.",
        "how_to_take": "Take once daily in the evening or at bedtime, as cholesterol synthesis peaks during sleep.",
        "precautions_and_side_effects": "May occasionally cause mild muscle aches. Inform your doctor if you experience persistent unexplained muscle tenderness.",
        "food_interaction": "Avoid large quantities of grapefruit or grapefruit juice, which can increase medication levels in your blood.",
    },
    "metformin": {
        "purpose": "An antidiabetic agent that improves insulin sensitivity and helps maintain balanced blood glucose levels.",
        "how_to_take": "Take with meals to minimize gastrointestinal discomfort.",
        "precautions_and_side_effects": "May cause initial metallic taste, bloating, or loose stools during the first 1-2 weeks. Stay well hydrated.",
        "food_interaction": "Take with breakfast or dinner. Strictly limit alcohol intake to avoid lactic acidosis risk.",
    },
    "pantoprazole": {
        "purpose": "A proton pump inhibitor (PPI) that decreases excess stomach acid production, healing acid reflux and ulcers.",
        "how_to_take": "Take 30 to 60 minutes before your first meal of the day with water. Swallow the tablet whole; do not crush or chew.",
        "precautions_and_side_effects": "Well tolerated. Mild headache or transient stomach pain may occasionally occur.",
        "food_interaction": "Must be taken on an empty stomach, at least 30 minutes before breakfast.",
    },
    "omeprazole": {
        "purpose": "Reduces stomach acid to relieve heartburn, GERD, and gastritis.",
        "how_to_take": "Take once daily in the morning 30-60 minutes before breakfast.",
        "precautions_and_side_effects": "Generally safe. Occasionally causes mild nausea, bloating, or headache.",
        "food_interaction": "Take on an empty stomach in the morning.",
    },
    "cetirizine": {
        "purpose": "A second-generation antihistamine that relieves allergy symptoms like sneezing, runny nose, itching, and hives.",
        "how_to_take": "Take once daily with water. Preferred at bedtime if you experience mild sleepiness.",
        "precautions_and_side_effects": "May cause mild drowsiness or dry mouth in sensitive individuals. Avoid operating heavy machinery if drowsy.",
        "food_interaction": "Can be taken with or without food. Avoid alcohol as it increases sedation.",
    },
    "losartan": {
        "purpose": "An angiotensin II receptor blocker (ARB) that relaxes blood vessels, lowering blood pressure and protecting kidneys.",
        "how_to_take": "Take once daily at the same time each day, with or without food.",
        "precautions_and_side_effects": "May cause mild dizziness when standing up quickly. Rise slowly from sitting or lying positions.",
        "food_interaction": "Avoid potassium supplements or high-potassium salt substitutes unless advised by your doctor.",
    },
    "amlodipine": {
        "purpose": "A calcium channel blocker that relaxes vascular smooth muscle, controlling high blood pressure and preventing angina.",
        "how_to_take": "Take once daily with water, morning or evening.",
        "precautions_and_side_effects": "Mild ankle swelling or flushing may occur. Consult your physician if swelling becomes uncomfortable.",
        "food_interaction": "Avoid large amounts of grapefruit juice.",
    },
}

class AIPrescriptionExplainerService:
    @staticmethod
    async def explain_prescription(
        consultation: Consultation,
        medical_profile: Optional[Dict[str, Any]] = None,
    ) -> PrescriptionExplanationResponse:
        """
        Explains patient prescription using OpenAI 'gpt-4o-mini' with token-optimized prompt.
        Falls back to comprehensive clinical pharmacotherapy engine if OpenAI key is not configured yet.
        """
        api_key = settings.OPENAI_API_KEY
        doctor_name = (
            consultation.doctor.user.full_name
            if (consultation.doctor and consultation.doctor.user)
            else "Consultant Physician"
        )

        if api_key and api_key.strip():
            try:
                return await AIPrescriptionExplainerService._call_openai(
                    api_key=api_key.strip(),
                    consultation=consultation,
                    doctor_name=doctor_name,
                    medical_profile=medical_profile,
                )
            except Exception as e:
                logger.warning(
                    f"OpenAI Prescription Explainer call error: {e}. Falling back to clinical rules engine."
                )

        return AIPrescriptionExplainerService._clinical_fallback(
            consultation=consultation,
            doctor_name=doctor_name,
            medical_profile=medical_profile,
        )

    @staticmethod
    async def _call_openai(
        api_key: str,
        consultation: Consultation,
        doctor_name: str,
        medical_profile: Optional[Dict[str, Any]] = None,
    ) -> PrescriptionExplanationResponse:
        """Invokes OpenAI gpt-4o-mini with constrained tokens and structured JSON schema."""
        client = AsyncOpenAI(api_key=api_key)

        rx_list = [
            {
                "medicine_name": p.medicine_name,
                "dosage": p.dosage,
                "frequency": p.frequency,
                "duration": p.duration,
                "instructions": p.instructions or "As directed",
            }
            for p in consultation.prescription_items
        ]

        patient_allergies = (
            medical_profile.get("allergies", [])
            if medical_profile and isinstance(medical_profile, dict)
            else []
        )

        prompt_data = {
            "diagnosis": consultation.diagnosis,
            "clinical_notes": consultation.clinical_notes,
            "doctor_instructions": consultation.special_instructions,
            "doctor_highlights": consultation.highlights,
            "known_allergies": patient_allergies,
            "prescriptions": rx_list,
        }

        system_prompt = (
            "You are an empathetic, clinical pharmacist AI assistant. "
            "Explain this prescription to the patient in warm, plain, easy-to-understand English. "
            "Keep the output concise to minimize token usage while remaining clinically accurate and safe. "
            "Return ONLY valid JSON matching this schema:\n"
            "{\n"
            '  "summary": "2-3 sentence overview of what the doctor diagnosed and what this treatment achieves",\n'
            '  "medicines": [\n'
            '    {\n'
            '      "medicine_name": "exact name from input",\n'
            '      "purpose": "plain english explanation of why this is prescribed",\n'
            '      "how_to_take": "exact instructions on how and when to swallow/apply",\n'
            '      "precautions_and_side_effects": "common precautions, key side effects, what to do",\n'
            '      "food_interaction": "food/drink instructions or null"\n'
            "    }\n"
            "  ],\n"
            '  "lifestyle_and_diet_recommendations": ["tip 1", "tip 2"],\n'
            '  "warning_signs_to_watch": ["red flag 1", "red flag 2"],\n'
            '  "general_advice": "Brief comforting closing advice"\n'
            "}"
        )

        model_name = settings.OPENAI_MODEL or "gpt-4o-mini"
        response = await client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(prompt_data, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=700,
        )

        content = response.choices[0].message.content or "{}"
        parsed = json.loads(content)

        medicines_out: List[MedicineExplanationItem] = []
        for m in parsed.get("medicines", []):
            medicines_out.append(
                MedicineExplanationItem(
                    medicine_name=m.get("medicine_name", "Prescribed Medication"),
                    purpose=m.get("purpose", "Supports clinical recovery."),
                    how_to_take=m.get("how_to_take", "Take exactly as directed by your physician."),
                    precautions_and_side_effects=m.get(
                        "precautions_and_side_effects", "Inform your doctor if unusual symptoms occur."
                    ),
                    food_interaction=m.get("food_interaction"),
                )
            )

        return PrescriptionExplanationResponse(
            consultation_id=consultation.id,
            diagnosis=consultation.diagnosis,
            doctor_name=doctor_name,
            ai_model_used=model_name,
            is_live_ai=True,
            summary=parsed.get(
                "summary",
                f"Treatment plan prescribed by Dr. {doctor_name} for {consultation.diagnosis}."
            ),
            medicines=medicines_out,
            lifestyle_and_diet_recommendations=parsed.get("lifestyle_and_diet_recommendations", []),
            warning_signs_to_watch=parsed.get("warning_signs_to_watch", []),
            general_advice=parsed.get(
                "general_advice",
                "Follow your dosage schedule diligently and complete the full course prescribed."
            ),
            created_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _clinical_fallback(
        consultation: Consultation,
        doctor_name: str,
        medical_profile: Optional[Dict[str, Any]] = None,
    ) -> PrescriptionExplanationResponse:
        """Deterministic, comprehensive clinical rules engine used when OpenAI key is pending."""
        medicines_out: List[MedicineExplanationItem] = []

        for p in consultation.prescription_items:
            med_clean = p.medicine_name.lower()
            matched_ref = None
            for key, ref in DRUG_REFERENCE_DATABASE.items():
                if key in med_clean:
                    matched_ref = ref
                    break

            if matched_ref:
                purpose = matched_ref["purpose"]
                how_to_take = f"Take {p.dosage}, {p.frequency.lower()} for {p.duration}. {p.instructions or matched_ref['how_to_take']}"
                precautions = matched_ref["precautions_and_side_effects"]
                food = matched_ref["food_interaction"]
            else:
                purpose = f"Prescribed by Dr. {doctor_name} to address symptoms associated with {consultation.diagnosis}."
                how_to_take = f"Take {p.dosage}, {p.frequency.lower()} for a duration of {p.duration}. {p.instructions or 'Take with a glass of water.'}"
                precautions = "Take at consistent times every day. If you miss a dose, take it as soon as remembered unless it is close to your next scheduled dose."
                food = "Take after a light meal unless instructed otherwise."

            medicines_out.append(
                MedicineExplanationItem(
                    medicine_name=p.medicine_name,
                    purpose=purpose,
                    how_to_take=how_to_take,
                    precautions_and_side_effects=precautions,
                    food_interaction=food,
                )
            )

        lifestyle_tips: List[str] = [
            "Maintain optimal daily hydration by drinking 2 to 2.5 liters of clean water.",
            "Ensure 7 to 8 hours of restful sleep to support your body's immune and tissue recovery.",
        ]
        if "fever" in consultation.diagnosis.lower() or "infection" in consultation.diagnosis.lower():
            lifestyle_tips.append("Get plenty of bed rest and monitor your body temperature twice daily.")
        if "angina" in consultation.diagnosis.lower() or "cardio" in consultation.diagnosis.lower() or "hypertension" in consultation.diagnosis.lower():
            lifestyle_tips.append("Consume a heart-healthy, low-sodium diet and avoid sudden strenuous physical exertion.")

        warning_signs: List[str] = [
            "Sudden severe allergic reaction (difficulty breathing, facial swelling, or severe hives).",
            "Persistent worsening of symptoms after 48-72 hours despite medication adherence.",
        ]
        if consultation.highlights:
            warning_signs.insert(0, f"Doctor Highlight: {consultation.highlights}")

        return PrescriptionExplanationResponse(
            consultation_id=consultation.id,
            diagnosis=consultation.diagnosis,
            doctor_name=doctor_name,
            ai_model_used="Clinical Pharmacology Engine (OpenAI gpt-4o-mini key pending in .env)",
            is_live_ai=False,
            summary=(
                f"Dr. {doctor_name} diagnosed you with {consultation.diagnosis}. "
                f"Your treatment plan includes {len(consultation.prescription_items)} medications designed to relieve your symptoms and promote recovery."
            ),
            medicines=medicines_out,
            lifestyle_and_diet_recommendations=lifestyle_tips,
            warning_signs_to_watch=warning_signs,
            general_advice="Store your medicines in a cool, dry place away from direct sunlight. Complete your treatment course as advised by your physician.",
            created_at=datetime.now(timezone.utc),
        )

ai_prescription_explainer = AIPrescriptionExplainerService()
