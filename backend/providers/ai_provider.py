"""
AI provider abstraction for pre-visit and post-visit summary generation.

Prompt templates are taken verbatim from the LLM Usage Guidance in
AGENT_SPEC.md so the documented contract and the implementation never drift
apart. See docs/ai-design.md for the full write-up.
"""
import abc
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

import httpx

from app.config import settings

# Exact prompt templates from AGENT_SPEC.md's "LLM Usage Guidance".
PRE_VISIT_PROMPT_TEMPLATE = (
    "Analyse these symptoms and return: urgency level (Low / Medium / High), "
    "chief complaint, and three suggested questions for the doctor. "
    "Symptoms: {symptoms}"
)

POST_VISIT_PROMPT_TEMPLATE = (
    "Convert these clinical notes into a patient-friendly summary with "
    "medication schedule and follow-up steps: {notes}"
)

# Appended to the spec's post-visit prompt so the medication schedule is built
# from what the doctor actually prescribed, not guessed from free-text notes.
POST_VISIT_PRESCRIPTION_TEMPLATE = "\n\nPrescription:\n{prescription}"

PRE_VISIT_SYSTEM_PROMPT = (
    "You are a clinical intake assistant. Given a patient's free-text "
    "symptom description, respond with ONLY a JSON object of the exact "
    "shape: "
    '{"urgency": "Low|Medium|High", "chief_complaint": "string", '
    '"suggested_questions": ["string", "string", "string"]}. '
    "Do not include any text outside the JSON object. Do not provide a "
    "diagnosis or medical advice."
)

POST_VISIT_SYSTEM_PROMPT = (
    "You are a patient-communication assistant. Given a doctor's clinical "
    "notes, respond with ONLY a JSON object of the exact shape: "
    '{"summary": "string", "medication_schedule": "string", '
    '"follow_up_steps": "string"}. '
    "Write in plain, patient-friendly language. Do not include any text "
    "outside the JSON object. Do not provide a new diagnosis. Build the "
    "medication schedule only from the Prescription section, keeping every "
    "medication's name, dosage, frequency and duration exactly as given; "
    "never add, remove or change a medication. If no medications are "
    "prescribed, say so."
)


@dataclass(frozen=True)
class PrescribedMedication:
    name: str
    dosage: str
    frequency: str
    duration_days: Optional[int] = None

    def describe(self) -> str:
        text = f"{self.name} {self.dosage}, {self.frequency}"
        if self.duration_days:
            text += f", for {self.duration_days} day{'s' if self.duration_days != 1 else ''}"
        return text


def format_prescription(
    medications: Sequence[PrescribedMedication], instructions: Optional[str]
) -> str:
    """Plain-text prescription block given to the LLM."""
    lines = [f"- {m.describe()}" for m in medications] or ["- No medications prescribed."]
    if instructions and instructions.strip():
        lines.append(f"Instructions: {instructions.strip()}")
    return "\n".join(lines)


class AIProviderError(Exception):
    """Base class for AI provider failures. Never allowed to touch appointment state."""


class AIProviderTimeoutError(AIProviderError):
    pass


class AIProviderUnavailableError(AIProviderError):
    pass


class AIProviderMalformedResponseError(AIProviderError):
    """Raised when the provider's response cannot even be parsed as JSON."""


class AIProvider(abc.ABC):
    """Abstraction over any LLM backend. Returns raw (unvalidated) dicts —
    schema validation is the caller's (AIService's) responsibility."""

    @abc.abstractmethod
    def generate_pre_visit_summary(self, symptoms: str) -> Dict[str, Any]:
        ...

    @abc.abstractmethod
    def generate_post_visit_summary(
        self,
        notes: str,
        medications: Sequence[PrescribedMedication] = (),
        prescription_instructions: Optional[str] = None,
    ) -> Dict[str, Any]:
        ...


class MockAIProvider(AIProvider):
    """Deterministic, offline provider used when DEMO_MODE is enabled.
    Never calls out to a network and always returns schema-shaped output."""

    _HIGH_URGENCY_KEYWORDS = (
        "chest pain", "severe", "unbearable", "difficulty breathing",
        "shortness of breath", "unconscious", "bleeding", "stroke"
    )
    _LOW_URGENCY_KEYWORDS = ("mild", "slight", "minor", "occasional")

    def generate_pre_visit_summary(self, symptoms: str) -> Dict[str, Any]:
        text = (symptoms or "").lower()
        if any(kw in text for kw in self._HIGH_URGENCY_KEYWORDS):
            urgency = "High"
        elif any(kw in text for kw in self._LOW_URGENCY_KEYWORDS):
            urgency = "Low"
        else:
            urgency = "Medium"

        chief_complaint = (symptoms or "").strip()[:200] or "Not specified"

        return {
            "urgency": urgency,
            "chief_complaint": chief_complaint,
            "suggested_questions": [
                "When did these symptoms first start?",
                "Have the symptoms been getting better, worse, or staying the same?",
                "Are you currently taking any medications for this?",
            ],
        }

    def generate_post_visit_summary(
        self,
        notes: str,
        medications: Sequence[PrescribedMedication] = (),
        prescription_instructions: Optional[str] = None,
    ) -> Dict[str, Any]:
        notes_text = (notes or "").strip() or "No additional notes provided."
        if medications:
            schedule = " ".join(f"{m.describe()}." for m in medications)
        else:
            schedule = "No medications were prescribed at this visit."
        if prescription_instructions and prescription_instructions.strip():
            schedule += f" {prescription_instructions.strip()}"
        return {
            "summary": f"Here is a summary of your visit: {notes_text}",
            "medication_schedule": schedule,
            "follow_up_steps": "Follow up with your doctor if symptoms persist or worsen. Attend any scheduled follow-up appointment.",
        }


class RealAIProvider(AIProvider):
    """Calls an OpenAI-compatible Chat Completions endpoint over HTTP.

    Any LLM provider exposing an OpenAI-compatible /chat/completions API can
    be used by pointing AI_PROVIDER_BASE_URL at it. Credentials and endpoint
    come exclusively from environment variables (see app/config.py) — never
    hardcoded.
    """

    def __init__(self):
        self._base_url = settings.AI_PROVIDER_BASE_URL
        self._api_key = settings.AI_PROVIDER_API_KEY
        self._model = settings.AI_PROVIDER_MODEL
        self._timeout = settings.AI_PROVIDER_TIMEOUT_SECONDS

    def _chat_completion(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        if not self._api_key:
            raise AIProviderUnavailableError("AI_PROVIDER_API_KEY is not configured.")

        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.2,
                },
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise AIProviderTimeoutError(f"AI provider request timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise AIProviderUnavailableError(f"AI provider request failed: {exc}") from exc

        if response.status_code >= 500:
            raise AIProviderUnavailableError(f"AI provider returned server error {response.status_code}")
        if response.status_code >= 400:
            raise AIProviderUnavailableError(f"AI provider returned error {response.status_code}: {response.text}")

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise AIProviderMalformedResponseError(f"Unexpected AI provider response shape: {exc}") from exc

        import json as _json
        try:
            return _json.loads(content)
        except (ValueError, TypeError) as exc:
            raise AIProviderMalformedResponseError(f"AI provider content is not valid JSON: {exc}") from exc

    def generate_pre_visit_summary(self, symptoms: str) -> Dict[str, Any]:
        prompt = PRE_VISIT_PROMPT_TEMPLATE.format(symptoms=symptoms)
        return self._chat_completion(PRE_VISIT_SYSTEM_PROMPT, prompt)

    def generate_post_visit_summary(
        self,
        notes: str,
        medications: Sequence[PrescribedMedication] = (),
        prescription_instructions: Optional[str] = None,
    ) -> Dict[str, Any]:
        prompt = POST_VISIT_PROMPT_TEMPLATE.format(notes=notes) + POST_VISIT_PRESCRIPTION_TEMPLATE.format(
            prescription=format_prescription(medications, prescription_instructions)
        )
        return self._chat_completion(POST_VISIT_SYSTEM_PROMPT, prompt)


def get_ai_provider() -> AIProvider:
    """Resolve the active provider based on current settings (read live, not cached,
    so DEMO_MODE toggles and test overrides take effect immediately).
    AI_DEMO_MODE, when set, overrides DEMO_MODE for this integration only."""
    if settings.ai_demo_mode:
        return MockAIProvider()
    return RealAIProvider()
