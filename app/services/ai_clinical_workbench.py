from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, Dict, List, Optional
from openai import AsyncOpenAI

from app.core.config import settings
from app.schemas.consultation import (
    ClinicalCopilotRequest,
    ClinicalCopilotResponse,
    DifferentialDiagnosisItem,
    DrugSafetyCheckItem,
    DrugSafetyCheckRequest,
    DrugSafetyCheckResponse,
    ExtractedPrescription,
    SuggestedLabOrderItem,
    VoiceToSoapRequest,
    VoiceToSoapResponse,
)

logger = logging.getLogger(__name__)

# Common clinical interaction rules for offline fallback & cross-validation
KNOWN_DRUG_INTERACTIONS = [
    {
        "drugs": ["aspirin", "ibuprofen"],
        "severity": "HIGH",
        "effect": "Concomitant use increases upper gastrointestinal mucosal ulceration and bleeding risk. Ibuprofen may also attenuate aspirin's cardioprotective antiplatelet effect.",
        "recommendation": "Separate dosing by at least 2 hours or substitute ibuprofen with paracetamol for analgesia.",
    },
    {
        "drugs": ["atorvastatin", "clarithromycin"],
        "severity": "HIGH",
        "effect": "Strong CYP3A4 inhibition significantly elevates atorvastatin plasma concentrations, increasing myopathy and rhabdomyolysis risk.",
        "recommendation": "Temporarily suspend atorvastatin during macrolide therapy or use an alternative antibiotic like azithromycin.",
    },
    {
        "drugs": ["atorvastatin", "erythromycin"],
        "severity": "HIGH",
        "effect": "CYP3A4 inhibition increases statin toxicity and muscle injury risks.",
        "recommendation": "Use non-interacting antimicrobial or switch statin temporarily.",
    },
    {
        "drugs": ["warfarin", "aspirin"],
        "severity": "HIGH",
        "effect": "Synergistic anticoagulant and antiplatelet effects markedly heighten hemorrhage and internal bleeding risk.",
        "recommendation": "Monitor INR closely or prescribe PPI gastroprotection under strict clinical supervision.",
    },
    {
        "drugs": ["metformin", "contrast"],
        "severity": "HIGH",
        "effect": "Risk of contrast-induced nephropathy leading to acute metformin accumulation and lactic acidosis.",
        "recommendation": "Withhold metformin 48 hours prior to and after iodinated contrast imaging.",
    },
    {
        "drugs": ["paracetamol", "acetaminophen"],
        "severity": "MEDIUM",
        "effect": "Duplicate acetaminophen components from multiple formulations can lead to cumulative hepatotoxicity exceeding 4,000 mg/day.",
        "recommendation": "Verify total daily acetaminophen dose across all combination products.",
    },
]

ALLERGY_CLASSES = {
    "penicillin": ["penicillin", "amoxicillin", "ampicillin", "augmentin", "piperacillin"],
    "sulfa": ["sulfamethoxazole", "bactrim", "septra", "sulfadiazine"],
    "aspirin": ["aspirin", "ecosprin", "acetylsalicylic acid", "disprin"],
    "nsaid": ["ibuprofen", "naproxen", "diclofenac", "ketorolac", "mefenamic"],
    "cephalosporin": ["cefixime", "ceftriaxone", "cephalexin", "cefuroxime"],
}

DISEASE_CONTRAINDICATIONS = [
    {
        "condition": "chronic kidney disease",
        "keywords": ["kidney", "renal", "ckd"],
        "drugs": ["ibuprofen", "diclofenac", "naproxen", "ketorolac"],
        "severity": "HIGH",
        "effect": "NSAIDs inhibit renal prostaglandins, reducing glomerular filtration rate and precipitating acute-on-chronic renal failure.",
        "recommendation": "Avoid NSAIDs. Use paracetamol (acetaminophen) or topical therapies.",
    },
    {
        "condition": "peptic ulcer disease",
        "keywords": ["ulcer", "gastric bleed", "gerd", "gastritis"],
        "drugs": ["ibuprofen", "aspirin", "diclofenac", "naproxen"],
        "severity": "HIGH",
        "effect": "Inhibition of COX-1 impairs gastric mucosal cytoprotection, triggering recurrent ulceration or life-threatening hemorrhage.",
        "recommendation": "Use paracetamol or add co-prescribed proton pump inhibitor (e.g. Pantoprazole 40mg).",
    },
    {
        "condition": "asthma",
        "keywords": ["asthma", "bronchospasm", "wheeze"],
        "drugs": ["aspirin", "ibuprofen", "propranolol", "atenolol"],
        "severity": "MEDIUM",
        "effect": "Non-selective beta-blockers or NSAIDs can trigger severe acute bronchospasm in sensitive asthmatic patients.",
        "recommendation": "Use cardioselective agents if beta-blocker is mandatory, and paracetamol for pain.",
    },
    {
        "condition": "hypertension",
        "keywords": ["hypertension", "high blood pressure", "htn"],
        "drugs": ["pseudoephedrine", "phenylephrine"],
        "severity": "MEDIUM",
        "effect": "Alpha-adrenergic decongestants produce systemic vasoconstriction and sudden blood pressure spikes.",
        "recommendation": "Use saline nasal irrigation or topical nasal steroid sprays instead.",
    },
]


class AIClinicalWorkbenchService:
    """
    AI-powered clinical copilot services for doctors using OpenAI gpt-4o-mini
    with low token consumption, structured JSON output, and clinical rule fallbacks.
    """

    @classmethod
    async def check_drug_safety(cls, req: DrugSafetyCheckRequest) -> DrugSafetyCheckResponse:
        """
        Feature 1: Real-Time Drug-Drug, Drug-Allergy & Drug-Disease Interaction Checker.
        """
        api_key = settings.OPENAI_API_KEY.strip() if settings.OPENAI_API_KEY else ""

        if api_key and len(api_key) > 8:
            try:
                client = AsyncOpenAI(api_key=api_key)
                prompt = f"""You are an expert clinical pharmacology safety engine.
Analyze this prescription for drug-drug interactions, drug-allergy contraindications, and drug-disease conflicts:

Prescribed Medicines: {', '.join(req.medicines)}
Known Patient Drug Allergies: {', '.join(req.allergies) if req.allergies else 'None documented'}
Patient Chronic Conditions: {', '.join(req.chronic_conditions) if req.chronic_conditions else 'None documented'}
Patient Age: {req.patient_age or 'Adult'}, Gender: {req.patient_gender or 'Unspecified'}

Return a strictly valid JSON object matching this schema:
{{
  "overall_safety": "SAFE" | "MODERATE_WARNING" | "CRITICAL_CONTRAINDICATION",
  "safety_score": 0-100 integer,
  "summary": "Concise 1-2 sentence clinical summary of prescription safety",
  "warnings_count": integer count of warnings,
  "interactions": [
    {{
      "interaction_type": "DRUG_DRUG" | "DRUG_ALLERGY" | "DRUG_DISEASE",
      "severity": "HIGH" | "MEDIUM" | "LOW",
      "primary_item": "Prescribed medicine name",
      "interacting_with": "The other drug, allergen, or condition",
      "clinical_effect": "Exact physiological mechanism or adverse risk",
      "clinical_recommendation": "Actionable doctor advice (e.g. discontinue, dose adjust, substitute)"
    }}
  ],
  "safer_alternatives": ["Suggested alternative medicine names if any high/medium contraindications exist"]
}}
Be clinically accurate, concise, and do not repeat disclaimers. If all drugs are safe, return overall_safety: SAFE and empty interactions."""

                response = await client.chat.completions.create(
                    model=settings.OPENAI_MODEL or "gpt-4o-mini",
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a hospital clinical pharmacology safety evaluator. Output strictly JSON.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                    max_tokens=650,
                )

                content = response.choices[0].message.content or "{}"
                data = json.loads(content)

                interactions = [
                    DrugSafetyCheckItem(**item) for item in data.get("interactions", [])
                ]
                return DrugSafetyCheckResponse(
                    overall_safety=data.get("overall_safety", "SAFE"),
                    safety_score=int(data.get("safety_score", 95)),
                    summary=data.get("summary", "Prescription safety review completed."),
                    warnings_count=len(interactions),
                    interactions=interactions,
                    safer_alternatives=data.get("safer_alternatives", []),
                    ai_model_used=settings.OPENAI_MODEL or "gpt-4o-mini",
                    is_live_ai=True,
                )
            except Exception as e:
                logger.warning(f"OpenAI Drug Safety evaluation failed, falling back to clinical rules: {e}")

        # Fallback to local clinical rule engine
        return cls._fallback_drug_safety(req)

    @classmethod
    def _fallback_drug_safety(cls, req: DrugSafetyCheckRequest) -> DrugSafetyCheckResponse:
        interactions: List[DrugSafetyCheckItem] = []
        meds_lower = [m.lower() for m in req.medicines]

        # 1. Check Drug-Allergy conflicts
        for allergy in req.allergies or []:
            a_clean = allergy.lower().strip()
            for med in req.medicines:
                m_clean = med.lower()
                # Check direct word match or class match
                is_allergic = False
                matched_class = a_clean
                for allergen_group, group_drugs in ALLERGY_CLASSES.items():
                    if allergen_group in a_clean:
                        if any(gd in m_clean for gd in group_drugs):
                            is_allergic = True
                            matched_class = allergen_group
                            break

                if not is_allergic and a_clean in m_clean:
                    is_allergic = True

                if is_allergic:
                    interactions.append(
                        DrugSafetyCheckItem(
                            interaction_type="DRUG_ALLERGY",
                            severity="HIGH",
                            primary_item=med,
                            interacting_with=f"Documented Allergy: {allergy}",
                            clinical_effect=f"Patient has a documented hypersensitivity to {matched_class}. High risk of anaphylaxis, severe urticaria, or angioedema.",
                            clinical_recommendation=f"Contraindicated. Immediately replace {med} with a non-cross-reactive alternative.",
                        )
                    )

        # 2. Check Drug-Disease conflicts
        for condition in req.chronic_conditions or []:
            c_clean = condition.lower()
            for rule in DISEASE_CONTRAINDICATIONS:
                if any(kw in c_clean for kw in rule["keywords"]):
                    for med in req.medicines:
                        if any(d in med.lower() for d in rule["drugs"]):
                            interactions.append(
                                DrugSafetyCheckItem(
                                    interaction_type="DRUG_DISEASE",
                                    severity=rule["severity"],
                                    primary_item=med,
                                    interacting_with=f"Chronic Condition: {condition}",
                                    clinical_effect=rule["effect"],
                                    clinical_recommendation=rule["recommendation"],
                                )
                            )

        # 3. Check Drug-Drug interactions
        for rule in KNOWN_DRUG_INTERACTIONS:
            d1, d2 = rule["drugs"]
            match1 = next((m for m in req.medicines if d1 in m.lower()), None)
            match2 = next((m for m in req.medicines if d2 in m.lower()), None)
            if match1 and match2 and match1 != match2:
                interactions.append(
                    DrugSafetyCheckItem(
                        interaction_type="DRUG_DRUG",
                        severity=rule["severity"],
                        primary_item=match1,
                        interacting_with=match2,
                        clinical_effect=rule["effect"],
                        clinical_recommendation=rule["recommendation"],
                    )
                )

        high_count = sum(1 for i in interactions if i.severity == "HIGH")
        med_count = sum(1 for i in interactions if i.severity == "MEDIUM")

        if high_count > 0:
            overall = "CRITICAL_CONTRAINDICATION"
            score = max(20, 100 - (high_count * 35) - (med_count * 15))
            summary = f"CRITICAL: Found {len(interactions)} significant interaction warning(s). High clinical risk detected."
        elif med_count > 0:
            overall = "MODERATE_WARNING"
            score = max(50, 100 - (med_count * 20))
            summary = f"WARNING: Found {len(interactions)} moderate interaction caution(s). Clinical monitoring advised."
        else:
            overall = "SAFE"
            score = 98
            summary = "No major drug interactions or allergy conflicts identified in the prescribed regimen."

        safer_alternatives = []
        if any("amoxicillin" in m.lower() for m in req.medicines) and any("penicillin" in a.lower() for a in req.allergies or []):
            safer_alternatives.append("Azithromycin 500mg (Macrolide) or Doxycycline 100mg")
        if any(any(n in m.lower() for n in ["ibuprofen", "diclofenac"]) for m in req.medicines):
            safer_alternatives.append("Paracetamol 650mg (Acetaminophen) for non-NSAID analgesia")

        return DrugSafetyCheckResponse(
            overall_safety=overall,
            safety_score=score,
            summary=summary,
            warnings_count=len(interactions),
            interactions=interactions,
            safer_alternatives=safer_alternatives,
            ai_model_used="Clinical Rule Engine (OpenAI key pending)",
            is_live_ai=False,
        )

    @classmethod
    async def get_clinical_copilot_guidance(
        cls, req: ClinicalCopilotRequest, catalog_tests: Optional[List[Dict[str, Any]]] = None
    ) -> ClinicalCopilotResponse:
        """
        Feature 2: Differential Diagnosis & Confirmatory Lab Test Assistant.
        """
        api_key = settings.OPENAI_API_KEY.strip() if settings.OPENAI_API_KEY else ""
        test_catalog_names = [t.get("name", "") for t in (catalog_tests or []) if t.get("name")]

        if api_key and len(api_key) > 8:
            try:
                client = AsyncOpenAI(api_key=api_key)
                prompt = f"""You are an advanced clinical decision support AI for outpatient hospital physicians.
Evaluate this patient clinical encounter:

Chief Complaint: {req.chief_complaint}
Symptoms & Onset: {req.symptoms or 'Not specified'}
Vitals: BP={req.vitals_bp or 'Normal'}, Pulse={req.vitals_heart_rate or 'Normal'} bpm, SpO2={req.vitals_spo2 or 'Normal'}%, Temp={req.vitals_temperature or 'Normal'} F
Chronic Medical History: {', '.join(req.chronic_conditions) if req.chronic_conditions else 'None'}
Patient: {req.patient_age or 'Adult'} years old, {req.patient_gender or 'Unspecified'}
Hospital Lab Catalog Available: {', '.join(test_catalog_names[:12]) if test_catalog_names else 'Standard panels'}

Output a strictly valid JSON matching this schema:
{{
  "summary_assessment": "Concise 1-2 sentence clinical impression",
  "differential_diagnoses": [
    {{
      "diagnosis": "Condition name",
      "likelihood": "HIGH" | "MODERATE" | "LOW",
      "clinical_rationale": "Key physiological/clinical features supporting this",
      "recommended_tests": ["Specific diagnostic test names"]
    }}
  ],
  "suggested_lab_orders": [
    {{
      "test_name": "Test name (prefer catalog matches like Complete Blood Count, ECG, Lipid Profile if relevant)",
      "urgency": "ROUTINE" | "URGENT" | "STAT",
      "clinical_justification": "Why this test confirms or rules out the condition"
    }}
  ],
  "red_flag_warnings": ["Urgent clinical signs that warrant immediate emergency escalation"],
  "recommended_physical_exams": ["Specific physical exam maneuvers or evaluations to perform"]
}}
Be concise, accurate, and output 2 to 3 differential diagnoses."""

                response = await client.chat.completions.create(
                    model=settings.OPENAI_MODEL or "gpt-4o-mini",
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a hospital clinical decision support copilot. Output strictly JSON.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                    max_tokens=700,
                )

                content = response.choices[0].message.content or "{}"
                data = json.loads(content)

                diffs = [DifferentialDiagnosisItem(**d) for d in data.get("differential_diagnoses", [])]
                labs = [SuggestedLabOrderItem(**l) for l in data.get("suggested_lab_orders", [])]

                return ClinicalCopilotResponse(
                    summary_assessment=data.get("summary_assessment", "Clinical evaluation formulated."),
                    differential_diagnoses=diffs,
                    suggested_lab_orders=labs,
                    red_flag_warnings=data.get("red_flag_warnings", []),
                    recommended_physical_exams=data.get("recommended_physical_exams", []),
                    ai_model_used=settings.OPENAI_MODEL or "gpt-4o-mini",
                    is_live_ai=True,
                )
            except Exception as e:
                logger.warning(f"OpenAI Clinical Copilot evaluation failed, using clinical fallback: {e}")

        # Deterministic clinical fallback
        return cls._fallback_clinical_copilot(req, catalog_tests)

    @classmethod
    def _fallback_clinical_copilot(
        cls, req: ClinicalCopilotRequest, catalog_tests: Optional[List[Dict[str, Any]]] = None
    ) -> ClinicalCopilotResponse:
        complaint = (req.chief_complaint or "").lower()
        symptoms = (req.symptoms or "").lower()
        full_text = f"{complaint} {symptoms}"

        diffs: List[DifferentialDiagnosisItem] = []
        labs: List[SuggestedLabOrderItem] = []
        red_flags: List[str] = []
        exams: List[str] = []

        if any(w in full_text for w in ["chest", "angina", "tightness", "palpitation"]):
            diffs = [
                DifferentialDiagnosisItem(
                    diagnosis="Stable Angina Pectoris / Coronary Artery Disease",
                    likelihood="HIGH",
                    clinical_rationale="Exertional retrosternal discomfort and cardiac risk profile warrant immediate coronary evaluation.",
                    recommended_tests=["12-Lead Electrocardiogram", "Fasting Lipid Profile", "Cardiac Enzymes / Troponin"],
                ),
                DifferentialDiagnosisItem(
                    diagnosis="Gastroesophageal Reflux Disease (GERD)",
                    likelihood="MODERATE",
                    clinical_rationale="Substernal burning exacerbated post-prandially or in supine position mimicking angina.",
                    recommended_tests=["Trial of PPI", "Upper Endoscopy if refractory"],
                ),
                DifferentialDiagnosisItem(
                    diagnosis="Costochondritis / Musculoskeletal Chest Wall Pain",
                    likelihood="LOW",
                    clinical_rationale="Localized tenderness on palpation of costochondral junctions, worsened with deep inspiration.",
                    recommended_tests=["Chest X-Ray"],
                ),
            ]
            labs = [
                SuggestedLabOrderItem(test_name="12-Lead Electrocardiogram", urgency="STAT", clinical_justification="Rule out ischemic ST-T changes or acute arrhythmia."),
                SuggestedLabOrderItem(test_name="Fasting Lipid Profile", urgency="ROUTINE", clinical_justification="Assess atherogenic dyslipidemia cardiovascular risk markers."),
            ]
            red_flags = ["Pain radiating to left jaw or arm lasting >15 min", "Diaphoresis, syncope, or acute dyspnea"]
            exams = ["Cardiac auscultation for murmurs/gallops", "Chest wall palpation for localized tenderness"]
            summary = "Cardiac evaluation prioritized: rule out acute coronary syndrome before attributing symptoms to musculoskeletal or GI etiology."

        elif any(w in full_text for w in ["cough", "fever", "breath", "cold", "sore throat"]):
            diffs = [
                DifferentialDiagnosisItem(
                    diagnosis="Acute Bronchitis / Upper Respiratory Tract Infection",
                    likelihood="HIGH",
                    clinical_rationale="Acute onset cough with mild pyrexia and mucosal irritation.",
                    recommended_tests=["Complete Blood Count", "Chest X-Ray if crackles present"],
                ),
                DifferentialDiagnosisItem(
                    diagnosis="Community-Acquired Pneumonia",
                    likelihood="MODERATE",
                    clinical_rationale="Fever with productive cough and potential consolidation crackles.",
                    recommended_tests=["Complete Blood Count", "Chest X-Ray (PA View)"],
                ),
            ]
            labs = [
                SuggestedLabOrderItem(test_name="Complete Blood Count (CBC)", urgency="ROUTINE", clinical_justification="Detect leukocytosis or neutrophilic shift indicative of bacterial infection."),
                SuggestedLabOrderItem(test_name="Chest X-Ray (PA View)", urgency="ROUTINE", clinical_justification="Evaluate lung parenchymal infiltrates or consolidation."),
            ]
            red_flags = ["SpO2 falling below 94% on room air", "Stridor, cyanosis, or respiratory rate >24/min"]
            exams = ["Bilateral pulmonary auscultation for wheezing or bronchial sounds", "Pharyngeal inspection"]
            summary = "Respiratory presentation consistent with tracheobronchial inflammation. Rule out lower airway consolidation."

        else:
            diffs = [
                DifferentialDiagnosisItem(
                    diagnosis="General Medical Presentation / Undifferentiated Consultation",
                    likelihood="MODERATE",
                    clinical_rationale="Symptoms warrant standard clinical physical examination and baseline metabolic screen.",
                    recommended_tests=["Complete Blood Count", "Basic Metabolic Panel"],
                ),
            ]
            labs = [
                SuggestedLabOrderItem(test_name="Complete Blood Count (CBC)", urgency="ROUTINE", clinical_justification="Baseline hematological screening."),
            ]
            red_flags = ["Altered mental status or acute physiological decompensation"]
            exams = ["Comprehensive systematic physical examination"]
            summary = "Baseline clinical consultation evaluation recommended."

        return ClinicalCopilotResponse(
            summary_assessment=summary,
            differential_diagnoses=diffs,
            suggested_lab_orders=labs,
            red_flag_warnings=red_flags,
            recommended_physical_exams=exams,
            ai_model_used="Clinical Decision Matrix (OpenAI key pending)",
            is_live_ai=False,
        )

    @classmethod
    async def convert_voice_to_soap(cls, req: VoiceToSoapRequest) -> VoiceToSoapResponse:
        """
        Feature 3: Ambient Voice & Dictation to Structured SOAP Clinical Notes Scribe.
        """
        api_key = settings.OPENAI_API_KEY.strip() if settings.OPENAI_API_KEY else ""

        if api_key and len(api_key) > 8:
            try:
                client = AsyncOpenAI(api_key=api_key)
                prompt = f"""You are a professional medical scribe AI.
Convert this raw doctor consultation voice transcript / dictation into formal clinical SOAP notes:

Raw Transcript / Dictation:
\"\"\"{req.dictation_text}\"\"\"

Known Context:
Chief Complaint: {req.chief_complaint or 'As dictated'}
Vitals: {req.vitals_summary or 'Normal clinical vitals'}
Patient: {req.patient_name or 'Patient'}

Return a strictly valid JSON object:
{{
  "subjective": "Concise medical narrative of patient history, presenting illness, timeline, and reported symptoms",
  "objective": "Formal physical examination findings and vitals review",
  "assessment": "Clinical impression, working diagnosis, and severity assessment",
  "plan": "Treatment plan: medications, diagnostic tests, lifestyle recommendations, and safety precautions",
  "structured_soap_notes": "Full unified formatted SOAP note suitable for the medical record",
  "suggested_diagnosis": "Clear short diagnosis string (e.g. 'Acute Bacterial Bronchitis')",
  "suggested_special_instructions": "Clear patient home advice (diet, hydration, rest)",
  "extracted_prescriptions": [
    {{
      "medicine_name": "Generic or brand name with strength",
      "dosage": "e.g. 1 tab",
      "frequency": "e.g. Twice daily (1-0-1)",
      "duration": "e.g. 5 days",
      "instructions": "e.g. After meals with water"
    }}
  ],
  "suggested_follow_up_days": 1 | 3 | 7 | 14 | 30 or null
}}
Extract prescriptions mentioned in the speech. If none explicitly mentioned, keep extracted_prescriptions empty."""

                response = await client.chat.completions.create(
                    model=settings.OPENAI_MODEL or "gpt-4o-mini",
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a licensed physician medical scribe. Output formal clinical SOAP notes strictly in JSON.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                    max_tokens=750,
                )

                content = response.choices[0].message.content or "{}"
                data = json.loads(content)

                rx_items = [
                    ExtractedPrescription(**p) for p in data.get("extracted_prescriptions", [])
                ]

                return VoiceToSoapResponse(
                    subjective=data.get("subjective", ""),
                    objective=data.get("objective", ""),
                    assessment=data.get("assessment", ""),
                    plan=data.get("plan", ""),
                    structured_soap_notes=data.get(
                        "structured_soap_notes",
                        f"S: {data.get('subjective')}\nO: {data.get('objective')}\nA: {data.get('assessment')}\nP: {data.get('plan')}",
                    ),
                    suggested_diagnosis=data.get("suggested_diagnosis", "Clinical Consultation"),
                    suggested_special_instructions=data.get("suggested_special_instructions", ""),
                    extracted_prescriptions=rx_items,
                    suggested_follow_up_days=data.get("suggested_follow_up_days"),
                    ai_model_used=settings.OPENAI_MODEL or "gpt-4o-mini",
                    is_live_ai=True,
                )
            except Exception as e:
                logger.warning(f"OpenAI Voice-to-SOAP failed, using clinical fallback: {e}")

        # Deterministic fallback parser
        return cls._fallback_voice_to_soap(req)

    @classmethod
    def _fallback_voice_to_soap(cls, req: VoiceToSoapRequest) -> VoiceToSoapResponse:
        raw = req.dictation_text.strip()
        cc = req.chief_complaint or "Outpatient medical evaluation"

        # Simple heuristic extraction
        subjective = f"Patient presents for clinical evaluation with chief complaint of: {cc}. Details from encounter: {raw}"
        objective = f"Vital Signs: {req.vitals_summary or 'BP 120/80 mmHg, Pulse 72 bpm, SpO2 98%, Temp 98.6°F'}. Physical examination conducted; patient alert, oriented, and cooperative."
        assessment = f"Working clinical impression consistent with: {cc}."
        plan = "Prescribed targeted pharmacotherapy, advised hydration and resting, and instructed patient on red-flag warning signs."

        full_notes = (
            f"SUBJECTIVE:\n{subjective}\n\n"
            f"OBJECTIVE:\n{objective}\n\n"
            f"ASSESSMENT:\n{assessment}\n\n"
            f"PLAN:\n{plan}"
        )

        extracted_rx: List[ExtractedPrescription] = []
        if any(w in raw.lower() for w in ["paracetamol", "panadol", "crocin"]):
            extracted_rx.append(ExtractedPrescription(medicine_name="Paracetamol 650mg", dosage="1 tablet", frequency="Thrice daily (1-1-1)", duration="3 days", instructions="After meals with water"))
        if any(w in raw.lower() for w in ["amoxicillin", "antibiotic", "augmentin"]):
            extracted_rx.append(ExtractedPrescription(medicine_name="Amoxicillin 500mg", dosage="1 capsule", frequency="Thrice daily (1-1-1)", duration="5 days", instructions="Complete full antibiotic course"))

        return VoiceToSoapResponse(
            subjective=subjective,
            objective=objective,
            assessment=assessment,
            plan=plan,
            structured_soap_notes=full_notes,
            suggested_diagnosis=cc.title(),
            suggested_special_instructions="Drink plenty of warm fluids, maintain adequate rest, and return immediately if symptoms worsen.",
            extracted_prescriptions=extracted_rx,
            suggested_follow_up_days=5,
            ai_model_used="Clinical Scribe Heuristic (OpenAI key pending)",
            is_live_ai=False,
        )
