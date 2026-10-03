import json
import logging
import re
from typing import Any, Dict, List, Optional
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)

class AITriageService:
    @staticmethod
    def calculate_mews(
        systolic_bp: int,
        heart_rate: int,
        respiratory_rate: int,
        temperature_f: float,
        consciousness_level: str = "ALERT",
    ) -> int:
        """
        Modified Early Warning Score (MEWS) clinical standard calculation.
        Scores >= 5 indicate acute clinical instability requiring emergency response.
        """
        score = 0

        # 1. Systolic BP
        if systolic_bp <= 70:
            score += 3
        elif 71 <= systolic_bp <= 80:
            score += 2
        elif 81 <= systolic_bp <= 100:
            score += 1
        elif 101 <= systolic_bp <= 199:
            score += 0
        else:  # >= 200
            score += 2

        # 2. Heart Rate
        if heart_rate <= 40:
            score += 2
        elif 41 <= heart_rate <= 50:
            score += 1
        elif 51 <= heart_rate <= 100:
            score += 0
        elif 101 <= heart_rate <= 110:
            score += 1
        elif 111 <= heart_rate <= 129:
            score += 2
        else:  # >= 130
            score += 3

        # 3. Respiratory Rate
        if respiratory_rate <= 8:
            score += 2
        elif 9 <= respiratory_rate <= 17:
            score += 0
        elif 18 <= respiratory_rate <= 20:
            score += 1
        elif 21 <= respiratory_rate <= 29:
            score += 2
        else:  # >= 30
            score += 3

        # 4. Temperature (°F)
        if temperature_f < 95.0:
            score += 2
        elif 95.0 <= temperature_f <= 101.1:
            score += 0
        else:  # >= 101.2°F
            score += 2

        # 5. Neurological (AVPU)
        c = consciousness_level.upper()
        if c == "ALERT":
            score += 0
        elif c == "VOICE":
            score += 1
        elif c == "PAIN":
            score += 2
        elif c == "UNRESPONSIVE":
            score += 3

        return score

    @staticmethod
    def calculate_news2(
        mews: int,
        spo2: float,
    ) -> int:
        """
        National Early Warning Score 2 (NEWS2) incorporates oxygen saturation.
        """
        score = mews
        if spo2 <= 91.0:
            score += 3
        elif 92.0 <= spo2 <= 93.0:
            score += 2
        elif 94.0 <= spo2 <= 95.0:
            score += 1
        return score

    @classmethod
    async def evaluate_vitals_with_history(
        cls,
        vitals: Dict[str, Any],
        medical_profile: Optional[Dict[str, Any]] = None,
        past_consultations: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates patient vitals using deterministic MEWS/NEWS2 algorithms
        augmented by Google AI Studio 'gemma-4-31b-it' contextual analysis of the patient's
        complete medical background (chronic illnesses, past surgeries, active medications).
        """
        systolic = vitals.get("systolic_bp", 120)
        diastolic = vitals.get("diastolic_bp", 80)
        hr = vitals.get("heart_rate", 75)
        rr = vitals.get("respiratory_rate", 16)
        temp_f = vitals.get("temperature_f", 98.6)
        spo2 = vitals.get("spo2", 98.0)
        glucose = vitals.get("blood_glucose")
        avpu = vitals.get("consciousness_level", "ALERT")
        symptoms = vitals.get("symptoms_notes") or ""

        mews = cls.calculate_mews(
            systolic_bp=systolic,
            heart_rate=hr,
            respiratory_rate=rr,
            temperature_f=temp_f,
            consciousness_level=avpu,
        )
        news2 = cls.calculate_news2(mews=mews, spo2=spo2)

        # Baseline clinical classification
        is_hard_critical = (
            mews >= 5
            or news2 >= 7
            or systolic >= 180
            or systolic <= 80
            or hr >= 135
            or hr <= 40
            or spo2 <= 88.0
            or avpu in ["PAIN", "UNRESPONSIVE"]
            or (glucose is not None and (glucose >= 400.0 or glucose <= 50.0))
        )

        api_key = settings.GOOGLE_AI_API_KEY
        if api_key:
            try:
                ai_result = await cls._call_gemma_triage(
                    api_key=api_key,
                    vitals=vitals,
                    mews=mews,
                    news2=news2,
                    medical_profile=medical_profile,
                    past_consultations=past_consultations,
                )
                # Ensure deterministic hard criticals are never downgraded by LLM
                if is_hard_critical:
                    ai_result["is_critical"] = True
                    ai_result["triage_level"] = "CRITICAL_EMERGENCY"
                ai_result["mews_score"] = mews
                ai_result["news2_score"] = news2
                return ai_result
            except Exception as e:
                logger.warning(f"Gemma triage call failed: {e}. Executing clinical heuristic fallback.")

        # Clinical heuristic fallback
        return cls._heuristic_triage_evaluation(
            vitals=vitals,
            mews=mews,
            news2=news2,
            is_hard_critical=is_hard_critical,
            medical_profile=medical_profile,
            past_consultations=past_consultations,
        )

    @classmethod
    async def _call_gemma_triage(
        cls,
        api_key: str,
        vitals: Dict[str, Any],
        mews: int,
        news2: int,
        medical_profile: Optional[Dict[str, Any]],
        past_consultations: Optional[List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
                                "You are a Senior Critical Care Triage Physician AI in a Hospital Emergency & Inpatient System. "
                                "Analyze the patient's incoming vital signs in direct correlation with their detailed medical history. "
                                "Identify if there is acute physiological deterioration, hypertensive emergency, sepsis, respiratory distress, "
                                "or decompensation of chronic disease.\n\n"
                                f"Current Vital Signs:\n"
                                f"- Blood Pressure: {vitals.get('systolic_bp')}/{vitals.get('diastolic_bp')} mmHg\n"
                                f"- Heart Rate: {vitals.get('heart_rate')} bpm\n"
                                f"- Respiratory Rate: {vitals.get('respiratory_rate')} breaths/min\n"
                                f"- SpO2: {vitals.get('spo2')}%\n"
                                f"- Temperature: {vitals.get('temperature_f')}°F\n"
                                f"- Blood Glucose: {vitals.get('blood_glucose')} mg/dL\n"
                                f"- AVPU Consciousness: {vitals.get('consciousness_level')}\n"
                                f"- Patient Symptoms: {vitals.get('symptoms_notes')}\n"
                                f"- Calculated MEWS: {mews}, NEWS2: {news2}\n\n"
                                f"Patient Long-Term Medical Profile:\n"
                                f"{json.dumps(medical_profile or {}, indent=2)}\n\n"
                                f"Past Diagnoses & Consultations:\n"
                                f"{json.dumps(past_consultations or [], indent=2)}\n\n"
                                "Instructions:\n"
                                "1. Determine if this case is 'CRITICAL_EMERGENCY', 'MODERATE_RISK', 'LOW_RISK', or 'NORMAL'.\n"
                                "2. If the patient has chronic cardiovascular, pulmonary, or renal history (e.g. CAD, prior stent, heart failure, asthma, CKD), "
                                "any moderate vital deviation must be strictly scrutinized for decompensation.\n"
                                "3. Provide a clear, professional medical explanation in 'ai_analysis'.\n"
                                "4. Provide an urgent 'clinical_recommendation' for the doctor/compounder and patient.\n"
                                "5. List identified risk factors.\n\n"
                                "Respond strictly with valid JSON with this exact schema:\n"
                                "{\n"
                                '  "triage_level": "CRITICAL_EMERGENCY" | "MODERATE_RISK" | "LOW_RISK" | "NORMAL",\n'
                                '  "is_critical": boolean,\n'
                                '  "ai_analysis": "string explaining physiological correlation with patient history",\n'
                                '  "clinical_recommendation": "string clinical guidance",\n'
                                '  "risk_factors_detected": ["string", "string"]\n'
                                "}"
                            )
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
        }

        candidate_models = [settings.AI_RECOMMENDER_MODEL, "gemma-4-26b-a4b-it", "gemini-2.5-flash"]
        candidate_models = list(dict.fromkeys(candidate_models))

        last_error = None
        parsed = None

        async with httpx.AsyncClient(timeout=25.0) as client:
            for model_name in candidate_models:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                try:
                    resp = await client.post(url, json=payload)
                    if resp.status_code != 200:
                        logger.warning(f"Gemma triage model {model_name} status {resp.status_code}: {resp.text[:120]}")
                        continue
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if not candidates:
                        continue
                    parts = candidates[0].get("content", {}).get("parts", [])
                    non_thought = [p["text"] for p in parts if not p.get("thought") and "text" in p]
                    raw_text = non_thought[-1] if non_thought else (parts[-1].get("text", "") if parts else "")

                    raw_text = raw_text.strip()
                    if raw_text.startswith("```"):
                        raw_text = re.sub(r"^```(?:json)?\n?", "", raw_text)
                        raw_text = re.sub(r"\n?```$", "", raw_text)

                    parsed = json.loads(raw_text)
                    logger.info(f"Successfully evaluated vitals triage with model {model_name}")
                    break
                except Exception as err:
                    logger.warning(f"Triage model {model_name} failed: {err}")
                    last_error = err

        if not parsed:
            raise RuntimeError(f"All AI triage candidate models failed. Last error: {last_error}")

        return {
            "triage_level": parsed.get("triage_level", "NORMAL"),
            "is_critical": bool(parsed.get("is_critical", False)),
            "ai_analysis": parsed.get("ai_analysis", "Vital signs evaluated."),
            "clinical_recommendation": parsed.get("clinical_recommendation", "Continue routine monitoring."),
            "risk_factors_detected": parsed.get("risk_factors_detected", []),
        }

    @classmethod
    def _heuristic_triage_evaluation(
        cls,
        vitals: Dict[str, Any],
        mews: int,
        news2: int,
        is_hard_critical: bool,
        medical_profile: Optional[Dict[str, Any]],
        past_consultations: Optional[List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """
        Robust deterministic clinical rules engine correlating history with vitals.
        """
        systolic = vitals.get("systolic_bp", 120)
        diastolic = vitals.get("diastolic_bp", 80)
        hr = vitals.get("heart_rate", 75)
        spo2 = vitals.get("spo2", 98.0)
        temp_f = vitals.get("temperature_f", 98.6)
        glucose = vitals.get("blood_glucose")
        symptoms = (vitals.get("symptoms_notes") or "").lower()

        chronic_conditions = []
        if medical_profile:
            chronic_conditions = [
                str(c.get("condition", "")).lower()
                for c in medical_profile.get("chronic_conditions", [])
            ]
        
        has_cardiac_history = any("card" in c or "heart" in c or "hypertens" in c or "infarct" in c for c in chronic_conditions)
        has_respiratory_history = any("asthma" in c or "copd" in c or "lung" in c for c in chronic_conditions)
        has_diabetic_history = any("diabet" in c for c in chronic_conditions)

        risk_factors: List[str] = []
        is_critical = is_hard_critical

        # Check cardiac exacerbation
        if has_cardiac_history and (systolic >= 160 or diastolic >= 100 or hr >= 110):
            is_critical = True
            risk_factors.append("Hypertensive/Cardiovascular exacerbation in patient with pre-existing heart disease")

        # Check respiratory decompensation
        if has_respiratory_history and spo2 <= 92.0:
            is_critical = True
            risk_factors.append("Acute hypoxemia in patient with chronic respiratory illness")

        # Check severe hyperglycemia or hypoglycemia
        if has_diabetic_history and glucose is not None:
            if glucose >= 300.0:
                is_critical = True
                risk_factors.append(f"Severe Hyperglycemia ({glucose} mg/dL) posing risk of DKA/HHS")
            elif glucose <= 65.0:
                is_critical = True
                risk_factors.append(f"Severe Hypoglycemia ({glucose} mg/dL) requiring urgent oral/IV glucose")

        # Check chest pain or dyspnea symptoms
        if "chest pain" in symptoms or "pressure" in symptoms or "shortness of breath" in symptoms or "dyspnea" in symptoms:
            if systolic >= 140 or hr >= 100 or spo2 <= 94.0:
                is_critical = True
                risk_factors.append("Red flag symptoms (chest pain / acute dyspnea) with abnormal hemodynamics")

        # Assign triage level
        if is_critical or mews >= 5 or news2 >= 7:
            triage_level = "CRITICAL_EMERGENCY"
            analysis = (
                f"CRITICAL CLINICAL ALERT: Patient vitals indicate acute physiological compromise (MEWS: {mews}, NEWS2: {news2}). "
                f"Systolic BP {systolic}/{diastolic} mmHg, Heart Rate {hr} bpm, SpO2 {spo2}%. "
            )
            if risk_factors:
                analysis += f"Key historical risk factors: {'; '.join(risk_factors)}. "
            analysis += "Immediate clinical escalation and emergency medical intervention required."
            recommendation = "Immediate physician examination required. Notify attending consultant and prepare emergency stabilization."
        elif mews >= 3 or news2 >= 5 or systolic >= 150 or hr >= 105:
            triage_level = "MODERATE_RISK"
            analysis = f"Moderate risk detected (MEWS: {mews}, NEWS2: {news2}). Elevated hemodynamics require close medical observation."
            recommendation = "Schedule prioritized consultation within 30-60 minutes. Recheck vitals every 30 minutes."
        elif mews >= 1 or news2 >= 2:
            triage_level = "LOW_RISK"
            analysis = f"Mild hemodynamic variance (MEWS: {mews}, NEWS2: {news2}). Baseline is largely stable."
            recommendation = "Continue standard clinical consultation queue. Routine vitals monitoring."
        else:
            triage_level = "NORMAL"
            analysis = "Physiological vital signs are within normal clinical thresholds. No acute distress observed."
            recommendation = "Standard routine care. No immediate clinical escalation required."

        return {
            "mews_score": mews,
            "news2_score": news2,
            "triage_level": triage_level,
            "is_critical": is_critical,
            "ai_analysis": analysis,
            "clinical_recommendation": recommendation,
            "risk_factors_detected": risk_factors,
        }

ai_triage_service = AITriageService()
