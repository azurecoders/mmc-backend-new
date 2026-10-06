from datetime import datetime, timezone
import json
import logging
import uuid
from typing import Any, Dict, List, Optional
from openai import AsyncOpenAI

from app.core.config import settings
from app.models.lab import LabOrder
from app.schemas.lab import (
    LabInterpretedParameter,
    LabReportSimplificationResponse,
)

logger = logging.getLogger(__name__)

# =====================================================================
# Deterministic Clinical Laboratory Reference Database
# =====================================================================

PARAM_CLINICAL_KNOWLEDGE: Dict[str, Dict[str, Any]] = {
    "hemoglobin": {
        "normal_low": 12.0,
        "normal_high": 17.5,
        "critical_low": 7.0,
        "unit": "g/dL",
        "low_patient": "Your red blood cell oxygen-carrying protein is below standard levels. This is commonly known as anemia and can cause fatigue, paleness, or feeling short of breath during exertion.",
        "low_doctor": "Microcytic/normocytic anemia. Recommend evaluating serum ferritin, iron saturation, CBC indices (MCV, MCH), and occult GI bleeding.",
        "high_patient": "Your hemoglobin is elevated, meaning you have a higher than normal concentration of red blood cells. This is frequently due to mild dehydration, smoking, or living at higher altitudes.",
        "high_doctor": "Erythrocytosis/polycythemia. Correlate with hydration status, pulse oximetry (rule out nocturnal hypoxemia/COPD), or JAK2 mutation if persistent.",
        "normal_patient": "Hemoglobin is within healthy reference limits, indicating good oxygen transportation capacity.",
    },
    "wbc": {
        "normal_low": 4500,
        "normal_high": 11000,
        "critical_high": 25000,
        "unit": "/µL",
        "low_patient": "Your white blood cell count is slightly low, which means your immune defense is currently mildly suppressed. This can happen after a viral bug or with certain medications.",
        "low_doctor": "Leukopenia. Monitor differential (ANC), review bone-marrow suppressing medications, and screen for viral post-infectious states.",
        "high_patient": "Your white blood cells are elevated. These cells are your body's immune defense soldiers; higher numbers indicate your immune system is actively fighting an infection or healing inflammation.",
        "high_doctor": "Leukocytosis. Look for acute bacterial infection, corticosteroid effect, tissue necrosis, or reactive inflammation. Check differential for neutrophilia/band forms.",
        "normal_patient": "White blood cell count is within healthy range, reflecting balanced immune activity.",
    },
    "platelet": {
        "normal_low": 150000,
        "normal_high": 450000,
        "critical_low": 50000,
        "unit": "/µL",
        "low_patient": "Platelets are clotting cells that prevent bruising and bleeding. Your count is low, so avoid contact sports and report any unexplained nosebleeds or skin bruising to your doctor.",
        "low_doctor": "Thrombocytopenia. Evaluate for viral clearance, drug-induced etiology (NSAIDs, antibiotics), splenomegaly, or immune-mediated consumption.",
        "high_patient": "Your platelet count is higher than standard limits, commonly caused by reactive inflammation or recent recovery from an illness.",
        "high_doctor": "Thrombocytosis. Differentiate reactive thrombocytosis (ferritin/CRP) from myeloproliferative disorders.",
        "normal_patient": "Platelet count is normal, indicating healthy blood clotting function.",
    },
    "glucose": {
        "normal_low": 70,
        "normal_high": 99,
        "critical_high": 250,
        "critical_low": 55,
        "unit": "mg/dL",
        "low_patient": "Your blood sugar is lower than normal. Mild low sugar can make you feel shaky, sweaty, or dizzy. Keep a fast-acting carb handy.",
        "low_doctor": "Hypoglycemia. Review antidiabetic medication timing (sulfonylureas/insulin) and fasting duration.",
        "high_patient": "Your fasting blood sugar is elevated above the 99 mg/dL threshold. If between 100-125, it indicates pre-diabetes; 126 or above suggests diabetes. It means your body is finding it difficult to process carbohydrates smoothly.",
        "high_doctor": "Hyperglycemia/impaired fasting glucose. Confirm with repeat fasting glucose or HbA1c. Initiate lifestyle modifications and review metabolic syndrome markers.",
        "normal_patient": "Fasting blood sugar is in the optimal range, showing healthy carbohydrate metabolism.",
    },
    "hba1c": {
        "normal_low": 4.0,
        "normal_high": 5.6,
        "unit": "%",
        "high_patient": "HbA1c measures your average blood sugar over the past 3 months. A value of 5.7–6.4% indicates pre-diabetes, and 6.5% or higher indicates diabetes. Consistent dietary adjustments can bring this number down.",
        "high_doctor": "Elevated glycation index. Initiate or adjust glycemic control therapy. Target < 7.0% for most adults, individualized by age and hypoglycemia risk.",
        "normal_patient": "Average 3-month blood sugar is in the healthy non-diabetic range.",
    },
    "cholesterol": {
        "normal_low": 120,
        "normal_high": 200,
        "unit": "mg/dL",
        "high_patient": "Your overall cholesterol is elevated. Excess circulating cholesterol can gradually build up in blood vessels. Reducing saturated and trans fats helps lower this.",
        "high_doctor": "Hypercholesterolemia. Evaluate full lipid panel (LDL, HDL, triglycerides) and calculate 10-year ASCVD risk score.",
        "normal_patient": "Total cholesterol is within healthy limits.",
    },
    "ldl": {
        "normal_low": 50,
        "normal_high": 100,
        "unit": "mg/dL",
        "high_patient": "LDL is often called 'bad cholesterol' because it carries fats that can deposit along arterial walls. Keeping it under 100 protects your heart.",
        "high_doctor": "Elevated LDL-C. Consider statin or dietary therapy based on primary/secondary cardiovascular prevention guidelines.",
        "normal_patient": "LDL cholesterol is optimal, supporting clean arterial blood flow.",
    },
    "triglyceride": {
        "normal_low": 40,
        "normal_high": 150,
        "critical_high": 500,
        "unit": "mg/dL",
        "high_patient": "Triglycerides are fats from unused calories, particularly sugars and refined carbohydrates. Elevated levels increase heart stress.",
        "high_doctor": "Hypertriglyceridemia. Address dietary sugars, alcohol intake, and physical activity. Watch for acute pancreatitis risk if >500 mg/dL.",
        "normal_patient": "Triglyceride levels are healthy.",
    },
    "creatinine": {
        "normal_low": 0.6,
        "normal_high": 1.3,
        "critical_high": 3.0,
        "unit": "mg/dL",
        "high_patient": "Creatinine is a natural waste product filtered out by your kidneys. Elevated levels suggest your kidneys are currently working harder or filtering more slowly. Staying well hydrated is important.",
        "high_doctor": "Elevated serum creatinine indicating acute kidney injury or chronic renal impairment. Review nephrotoxic drugs (NSAIDs, ACEi/ARBs) and calculate eGFR.",
        "normal_patient": "Serum creatinine is normal, indicating healthy kidney filtration.",
    },
    "uric_acid": {
        "normal_low": 3.0,
        "normal_high": 7.0,
        "unit": "mg/dL",
        "high_patient": "Your uric acid is high. Excess uric acid can form tiny sharp crystals in joints (especially the big toe, causing gout attacks) or lead to kidney stones. Drink plenty of water and avoid high-purine foods like red meat and beer.",
        "high_doctor": "Hyperuricemia. Screen for gouty arthritis, nephrolithiasis, or metabolic syndrome. Assess dietary purines, fructose intake, and loop diuretics.",
        "normal_patient": "Uric acid is within normal reference limits.",
    },
    "bilirubin": {
        "normal_low": 0.2,
        "normal_high": 1.2,
        "unit": "mg/dL",
        "high_patient": "Bilirubin is a yellow compound from broken-down red blood cells, processed by the liver. Elevated levels can sometimes cause mild yellowing of the eyes or dark urine.",
        "high_doctor": "Hyperbilirubinemia. Fractionate direct vs indirect bilirubin. Differentiate biliary obstruction/cholestasis from hemolysis or Gilbert's syndrome.",
        "normal_patient": "Total bilirubin is normal, indicating healthy liver processing.",
    },
    "alt": {
        "normal_low": 7,
        "normal_high": 56,
        "unit": "U/L",
        "high_patient": "ALT (SGPT) is a liver enzyme. When liver cells are irritated (by medications, fatty liver, or alcohol), they release ALT into the bloodstream.",
        "high_doctor": "Elevated ALT reflecting hepatocellular injury. Screen for NAFLD/NASH, viral hepatitis, hepatotoxic medications, or alcohol use.",
        "normal_patient": "Liver enzyme ALT is within normal healthy limits.",
    },
    "tsh": {
        "normal_low": 0.4,
        "normal_high": 4.0,
        "unit": "µIU/mL",
        "high_patient": "TSH is the pituitary hormone that stimulates your thyroid gland. High TSH means your thyroid is underactive (Hypothyroidism), which can cause sluggishness, weight gain, or cold sensitivity.",
        "high_doctor": "Elevated TSH indicative of primary hypothyroidism. Check Free T4 and anti-TPO antibodies. Initiate or titrate levothyroxine as clinically indicated.",
        "low_patient": "Low TSH indicates your thyroid gland may be overactive (Hyperthyroidism), speeding up metabolism and causing rapid heart rate or sweating.",
        "low_doctor": "Suppressed TSH indicating hyperthyroidism/thyrotoxicosis. Evaluate Free T3/T4, radioactive iodine uptake, or thyroid receptor antibodies.",
        "normal_patient": "Thyroid stimulating hormone (TSH) is well balanced.",
    },
}

class AILabSimplifierService:
    @staticmethod
    def _parse_numeric(val: Any) -> Optional[float]:
        try:
            cleaned = str(val).replace(",", "").replace("<", "").replace(">", "").strip()
            return float(cleaned)
        except Exception:
            return None

    @staticmethod
    def _match_biomarker(name: str) -> Optional[str]:
        n = name.lower()
        if "hemo" in n or "hgb" in n:
            return "hemoglobin"
        if "wbc" in n or "white blood" in n or "leukocyte" in n:
            return "wbc"
        if "platelet" in n or "plt" in n:
            return "platelet"
        if "fasting" in n and "glucose" in n or "blood sugar" in n or "fbs" in n:
            return "glucose"
        if "hba1c" in n or "a1c" in n or "glycated" in n:
            return "hba1c"
        if "ldl" in n:
            return "ldl"
        if "triglyceride" in n or "tg" in n:
            return "triglyceride"
        if "cholesterol" in n:
            return "cholesterol"
        if "creatinine" in n:
            return "creatinine"
        if "uric" in n:
            return "uric_acid"
        if "bilirubin" in n:
            return "bilirubin"
        if "sgpt" in n or "alt" in n:
            return "alt"
        if "tsh" in n or "thyroid" in n:
            return "tsh"
        return None

    @staticmethod
    def _fallback_interpret(
        test_name: str,
        test_category: str,
        patient_name: str,
        result_summary: str,
        findings_json: Optional[Dict[str, Any]],
        order_id: Optional[uuid.UUID] = None,
    ) -> LabReportSimplificationResponse:
        """
        Deterministic, clinically accurate fallback interpretation engine.
        Evaluates parameters against reference database.
        """
        interpreted_params: List[LabInterpretedParameter] = []
        critical_flags: List[str] = []
        abnormal_count = 0

        # Check findings_json if present
        raw_items: List[Dict[str, Any]] = []
        if findings_json:
            if isinstance(findings_json.get("parameters"), list):
                raw_items = findings_json["parameters"]
            elif isinstance(findings_json, dict):
                for k, v in findings_json.items():
                    if k == "parameters":
                        continue
                    if isinstance(v, dict):
                        raw_items.append({"parameter": k, **v})
                    else:
                        raw_items.append({"parameter": k, "value": str(v)})

        for item in raw_items:
            p_name = item.get("parameter") or item.get("name") or "Marker"
            val_str = str(item.get("value") or "").strip()
            unit_str = str(item.get("unit") or "").strip()
            ref_str = str(item.get("reference_range") or item.get("normal_range") or "").strip()
            flag_str = str(item.get("flag") or "NORMAL").upper()

            matched_key = AILabSimplifierService._match_biomarker(p_name)
            numeric_val = AILabSimplifierService._parse_numeric(val_str)

            status = flag_str if flag_str in ["HIGH", "LOW", "CRITICAL"] else "NORMAL"
            plain_meaning = f"{p_name} is within expected standard ranges."
            doc_significance = f"{p_name} stable within normal limits."

            if matched_key and matched_key in PARAM_CLINICAL_KNOWLEDGE:
                ref = PARAM_CLINICAL_KNOWLEDGE[matched_key]
                if not unit_str and ref.get("unit"):
                    unit_str = ref["unit"]
                if not ref_str:
                    ref_str = f"{ref['normal_low']} - {ref['normal_high']}"

                if numeric_val is not None:
                    if ref.get("critical_high") and numeric_val >= ref["critical_high"]:
                        status = "CRITICALLY_HIGH"
                        abnormal_count += 1
                        critical_flags.append(f"Critically High {p_name} ({val_str} {unit_str})")
                        plain_meaning = f"CRITICAL: {ref.get('high_patient', '')} This value is substantially above safety thresholds."
                        doc_significance = f"Critical elevation. {ref.get('high_doctor', '')}"
                    elif ref.get("critical_low") and numeric_val <= ref["critical_low"]:
                        status = "CRITICALLY_LOW"
                        abnormal_count += 1
                        critical_flags.append(f"Critically Low {p_name} ({val_str} {unit_str})")
                        plain_meaning = f"CRITICAL: {ref.get('low_patient', '')} This value is dangerously low."
                        doc_significance = f"Critical drop. {ref.get('low_doctor', '')}"
                    elif numeric_val > ref["normal_high"]:
                        status = "ELEVATED"
                        abnormal_count += 1
                        plain_meaning = ref.get("high_patient", f"{p_name} is higher than reference limits.")
                        doc_significance = ref.get("high_doctor", f"Elevated {p_name}.")
                    elif numeric_val < ref["normal_low"]:
                        status = "LOW"
                        abnormal_count += 1
                        plain_meaning = ref.get("low_patient", f"{p_name} is lower than reference limits.")
                        doc_significance = ref.get("low_doctor", f"Subnormal {p_name}.")
                    else:
                        status = "NORMAL"
                        plain_meaning = ref.get("normal_patient", f"{p_name} is within healthy range.")
                        doc_significance = "Within standard reference interval."

            interpreted_params.append(
                LabInterpretedParameter(
                    parameter_name=p_name,
                    measured_value=f"{val_str} {unit_str}".strip(),
                    reference_range=ref_str or "Standard reference limits",
                    status=status,
                    plain_english_meaning=plain_meaning,
                    clinical_significance=doc_significance,
                )
            )

        # Overall Status
        if critical_flags:
            overall_status = "CRITICAL_ALERT"
            patient_summary = (
                f"Your diagnostic report for {test_name} contains one or more critical values that require prompt medical attention. "
                f"Please review the highlighted values with your doctor immediately."
            )
            doctor_snapshot = (
                f"CRITICAL LAB ALERT: Out-of-range critical values detected: {', '.join(critical_flags)}. "
                f"Immediate clinical reassessment, vital stabilization, and potential confirmatory stat retest indicated."
            )
        elif abnormal_count > 0:
            overall_status = "ATTENTION_NEEDED"
            patient_summary = (
                f"Your {test_name} results show {abnormal_count} marker(s) that are mildly out of normal range. "
                "There is no need to panic—out-of-range markers are very common and often relate to temporary inflammation, hydration, or dietary factors. "
                "Your doctor will guide you on lifestyle adjustments or follow-up."
            )
            doctor_snapshot = (
                f"{test_name} completed with {abnormal_count} abnormal parameter(s). "
                f"Primary findings: {result_summary or 'See parameter breakdown'}. Recommend clinical correlation and routine follow-up."
            )
        else:
            overall_status = "NORMAL"
            patient_summary = (
                f"Great news! Your {test_name} results are completely within normal, healthy ranges. "
                "All primary biological indicators meet standard laboratory safety benchmarks."
            )
            doctor_snapshot = (
                f"{test_name} within normal reference limits. "
                f"Summary: {result_summary or 'All measured analytes normal'}. No immediate diagnostic intervention needed."
            )

        questions = [
            "Are my out-of-range markers something that can be managed with diet and lifestyle changes?",
            "Do I need a repeat test in 4 to 8 weeks to track improvement?",
            "Do any of my current daily medications impact these specific lab values?",
        ]

        actions = [
            "Share this simplified summary with your treating physician at your next follow-up.",
            "Stay well hydrated with fresh water to support kidney and blood filtration.",
            "Maintain a balanced diet avoiding excess processed foods and high sodium.",
        ]

        return LabReportSimplificationResponse(
            order_id=order_id,
            test_name=test_name,
            test_category=test_category,
            patient_name=patient_name,
            overall_status=overall_status,
            is_abnormal=(abnormal_count > 0 or len(critical_flags) > 0),
            patient_summary=patient_summary,
            doctor_snapshot=doctor_snapshot,
            critical_flags=critical_flags,
            interpreted_parameters=interpreted_params,
            questions_for_doctor=questions,
            recommended_actions=actions,
            ai_model_used="Hospital Laboratory Reference Rule Engine (Deterministic Protocol)",
            is_live_ai=False,
            generated_at=datetime.now(timezone.utc),
        )

    @staticmethod
    async def simplify_lab_report(
        test_name: str,
        test_category: str,
        patient_name: str,
        result_summary: str,
        findings_json: Optional[Dict[str, Any]] = None,
        order_id: Optional[uuid.UUID] = None,
        patient_age: Optional[int] = None,
        patient_gender: Optional[str] = None,
        clinical_diagnosis: Optional[str] = None,
    ) -> LabReportSimplificationResponse:
        """
        Interprets diagnostic laboratory report using OpenAI gpt-4o-mini with low token usage (~750 tokens).
        Gracefully falls back to deterministic clinical reference database if OpenAI API is offline.
        """
        api_key = settings.OPENAI_API_KEY
        if api_key and api_key.strip():
            try:
                client = AsyncOpenAI(api_key=api_key)
                system_prompt = (
                    "You are an expert Clinical Laboratory Pathologist and Patient Health Educator. "
                    "You interpret diagnostic lab findings for both PATIENTS (plain English, empathetic, reassuring, no medical jargon) "
                    "and CLINICIANS (high-density clinical differential snapshot). "
                    "Output STRICT JSON conforming to the requested schema."
                )

                findings_text = ""
                if findings_json:
                    findings_text = json.dumps(findings_json, indent=2)

                user_prompt = f"""
Test Name: {test_name} ({test_category})
Patient Name: {patient_name}
Patient Age: {patient_age or 'Adult'} | Gender: {patient_gender or 'Unspecified'}
Clinical Diagnosis Context: {clinical_diagnosis or 'Outpatient Evaluation'}
Lab Assistant Summary: {result_summary}
Findings Data:
{findings_text or 'No raw numerical parameters provided'}

Analyze all parameters against standard medical reference ranges and generate:
{{
  "overall_status": "NORMAL | ATTENTION_NEEDED | CRITICAL_ALERT",
  "is_abnormal": true / false,
  "patient_summary": "Friendly, plain-English explanation (3-4 sentences) reassuring the patient and clarifying findings without panic.",
  "doctor_snapshot": "Dense clinical bullet points for physicians noting exact out-of-range markers, potential differentials, and suggested retest intervals.",
  "critical_flags": ["List of any immediate danger values e.g. Platelets < 50k, Potassium > 6.0"],
  "interpreted_parameters": [
    {{
      "parameter_name": "Hemoglobin",
      "measured_value": "10.2 g/dL",
      "reference_range": "13.5 - 17.5 g/dL",
      "status": "NORMAL | ELEVATED | LOW | CRITICALLY_HIGH | CRITICALLY_LOW",
      "plain_english_meaning": "What this marker does and why being slightly low matters in plain terms.",
      "clinical_significance": "Pathophysiological note for doctors (e.g. Microcytic anemia, evaluate iron stores)."
    }}
  ],
  "questions_for_doctor": [
    "2-3 smart questions for the patient to ask their physician"
  ],
  "recommended_actions": [
    "2-3 healthy dietary, hydration, or lifestyle action steps"
  ]
}}
"""

                response = await client.chat.completions.create(
                    model=settings.OPENAI_MODEL,  # gpt-4o-mini
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                    max_tokens=1400,
                )

                content = response.choices[0].message.content or "{}"
                data = json.loads(content)

                raw_params = data.get("interpreted_parameters") or data.get("parameters") or []
                interpreted: List[LabInterpretedParameter] = []
                for p in raw_params:
                    try:
                        if isinstance(p, dict):
                            interpreted.append(LabInterpretedParameter(**p))
                    except Exception:
                        pass

                if not interpreted and (findings_json or result_summary):
                    fallback_res = AILabSimplifierService._fallback_interpret(
                        test_name=test_name,
                        test_category=test_category,
                        patient_name=patient_name,
                        result_summary=result_summary,
                        findings_json=findings_json,
                        order_id=order_id,
                    )
                    interpreted = fallback_res.interpreted_parameters

                raw_doc = data.get("doctor_snapshot")
                if isinstance(raw_doc, list):
                    doctor_snapshot = "\n• " + "\n• ".join([str(x) for x in raw_doc])
                elif isinstance(raw_doc, str):
                    doctor_snapshot = raw_doc
                else:
                    doctor_snapshot = result_summary

                raw_pat = data.get("patient_summary")
                if isinstance(raw_pat, list):
                    patient_summary = " ".join([str(x) for x in raw_pat])
                elif isinstance(raw_pat, str):
                    patient_summary = raw_pat
                else:
                    patient_summary = "Laboratory findings completed."

                return LabReportSimplificationResponse(
                    order_id=order_id,
                    test_name=test_name,
                    test_category=test_category,
                    patient_name=patient_name,
                    overall_status=data.get("overall_status", "ATTENTION_NEEDED" if data.get("is_abnormal") else "NORMAL"),
                    is_abnormal=bool(data.get("is_abnormal", False)),
                    patient_summary=patient_summary,
                    doctor_snapshot=doctor_snapshot,
                    critical_flags=data.get("critical_flags", []),
                    interpreted_parameters=interpreted,
                    questions_for_doctor=data.get("questions_for_doctor", []),
                    recommended_actions=data.get("recommended_actions", []),
                    ai_model_used=f"{settings.OPENAI_MODEL} (Live Clinical AI)",
                    is_live_ai=True,
                    generated_at=datetime.now(timezone.utc),
                )
            except Exception as e:
                logger.warning(
                    f"OpenAI lab report simplification error: {e}. Falling back to deterministic laboratory reference engine."
                )

        # Deterministic Fallback
        return AILabSimplifierService._fallback_interpret(
            test_name=test_name,
            test_category=test_category,
            patient_name=patient_name,
            result_summary=result_summary,
            findings_json=findings_json,
            order_id=order_id,
        )


ai_lab_simplifier = AILabSimplifierService()
