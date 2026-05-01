# AI Health Chat Integration

VitalSense can support an AI chat experience as a patient check-in and doctor
handoff assistant. The chat should be framed as health support and triage, not
as a diagnosis engine.

## Product goal

Add a conversational panel that asks questions like:

- "How are you feeling today?"
- "Are you dizzy, short of breath, in pain, or unusually tired?"
- "Did you take your medication today?"
- "Do you want me to share this with your doctor?"

The assistant should combine the patient's self-reported symptoms with the
latest wearable data and produce:

- a short patient-friendly response
- red-flag detection and escalation guidance
- a structured summary for the doctor
- optional event logging in the patient timeline

## Safety boundaries

The assistant must:

- clearly say it is not a doctor and cannot diagnose
- encourage emergency help for severe symptoms
- never tell a patient to ignore dangerous symptoms
- never change medication instructions
- avoid definitive diagnosis language
- escalate to SOS workflow when the patient reports emergency red flags

Emergency red flags include:

- chest pain or pressure
- severe shortness of breath
- fainting or loss of consciousness
- stroke-like symptoms such as face drooping, arm weakness, speech trouble
- severe allergic reaction
- suicidal intent or self-harm intent
- confusion with very abnormal vitals

For those cases, the response should be direct:

> This may be urgent. Please call emergency services now or ask someone nearby
> to help. I can also alert your family and doctor through VitalSense.

## Suggested user experience

Place the chat as a dashboard card below the vitals/risk area:

- compact message history
- input placeholder: "How are you feeling today?"
- quick chips: `dizzy`, `chest pain`, `short breath`, `tired`, `fever`, `I'm okay`
- "Share summary with doctor" button
- "Trigger SOS" button shown only for urgent classifications

The first assistant message can be:

> How are you feeling today? I can compare what you tell me with your latest
> heart rate and temperature and help prepare a note for your doctor.

## Backend API shape

Recommended endpoints:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/chat/{patient_id}` | Send a patient message and receive assistant reply |
| `GET` | `/api/chat/{patient_id}` | Fetch recent chat turns |
| `POST` | `/api/chat/{patient_id}/share` | Save/share doctor summary |

Example request:

```json
{
  "message": "I feel dizzy and my chest feels tight",
  "include_snapshot": true
}
```

Example response:

```json
{
  "reply": "Chest tightness with dizziness can be urgent. Please call emergency services now or ask someone nearby to help. I can alert your family and doctor through VitalSense.",
  "urgency": "emergency",
  "recommended_action": "trigger_sos",
  "doctor_summary": "Patient reports dizziness and chest tightness. Latest telemetry should be reviewed immediately.",
  "event_logged": true
}
```

## Data model

Add a `ChatMessage` model:

```python
class ChatRole(str, Enum):
    PATIENT = "patient"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatMessage(BaseModel):
    id: str = Field(default_factory=_new_id)
    patient_id: str
    role: ChatRole
    content: str
    urgency: str = "routine"
    created_at: datetime = Field(default_factory=_now)
    metadata: dict = Field(default_factory=dict)
```

Repository methods:

```python
def append_chat_message(self, message: ChatMessage) -> ChatMessage: ...
def recent_chat_messages(self, patient_id: str, limit: int = 30) -> list[ChatMessage]: ...
```

## AI service contract

Add a service boundary so the rest of the app does not depend on one vendor:

```python
class HealthChatService:
    def respond(self, patient: Patient, message: str) -> ChatResult:
        ...
```

`HealthChatService` should receive:

- patient profile
- personalized thresholds
- latest health snapshot
- recent events
- recent chat turns

It should return:

- assistant reply
- urgency: `routine`, `watch`, `urgent`, `emergency`
- recommended action: `none`, `verify`, `share_doctor`, `trigger_sos`
- doctor summary

## Prompt policy

The system prompt should enforce:

- supportive tone
- no diagnosis
- no medication changes
- always prioritize emergency services for red flags
- use the latest vitals as context, not as sole proof
- ask one concise follow-up question when symptoms are unclear
- produce a doctor summary in structured language

## Fallback mode

If no AI API key is configured, use a rule-based fallback:

- detect red-flag phrases
- classify urgency
- generate a templated response
- still create a doctor summary

This keeps demos working without external credentials.

## Implementation plan

1. Add `ChatMessage`, `ChatResult`, and urgency enums.
2. Add repository chat storage for in-memory and Firestore.
3. Add `HealthChatService` with rule-based fallback.
4. Add optional LLM provider behind an interface.
5. Add `/api/chat/{patient_id}` routes.
6. Add dashboard chat card with quick symptom chips.
7. Log urgent chat classifications as timeline events.
8. If urgency is `emergency`, offer one-click SOS escalation.

## Privacy notes

Chat content is health data. Treat it like telemetry:

- require authentication
- avoid logging raw chat text to server logs
- store only what the app needs
- expose chat history only to authorized patient/doctor views
- document retention policy before production use
