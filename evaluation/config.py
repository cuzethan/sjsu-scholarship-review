"""
config.py — central configuration for the Bedrock model evaluation harness.

Everything tunable lives here: model shortlist, sampling size, deterministic
inference settings, paths, and the rubric-per-scholarship mapping.

The harness reads xlsx files from LOCAL directories (the user uploads them);
it never reads from S3.
"""

from pathlib import Path

# --- AWS ---
AWS_PROFILE = "Samson"
AWS_REGION = "us-west-2"

# --- Paths ---
REPO_ROOT = Path(__file__).resolve().parent.parent
PARSER_DIR = REPO_ROOT / "Parser"           # reuse existing parser logic
PROMPTS_DIR = REPO_ROOT / "prompts"          # scholarship rubric/system prompts
INPUT_DIR = Path(__file__).resolve().parent / "input"
APPLICATIONS_DIR = INPUT_DIR / "applications"  # user drops application "ad hoc report" xlsx here
SCORES_DIR = INPUT_DIR / "scores"              # user drops human score sheets here
OUTPUT_DIR = Path(__file__).resolve().parent / "output"

# --- Sampling / fairness ---
SAMPLE_PER_SCHOLARSHIP = 20   # target applications per eligible scholarship/year
RANDOM_SEED = 42              # reproducible sampling

# Deterministic inference settings (fairness across models)
TEMPERATURE = 0.0
TOP_P = 1.0
MAX_TOKENS = 2048

# --- Phase 1 scope: SJSU General ONLY ---
# Evaluation mode is narrowed to SJSU General. Only applications whose rubric_id
# is in EVAL_SCOPE_RUBRIC_IDS are evaluated against human scores.
EVAL_SCOPE_RUBRIC_IDS = {"sjsu-general"}

# rubric_id -> rubric prompt markdown file. Phase 1 uses the single SJSU General
# rubric for both 25-26 and 26-27. Specialized rubrics are UNSUPPORTED stubs
# (kept for extensibility; not evaluated in phase 1).
RUBRIC_FILES = {
    "sjsu-general": "GeneralRubric.md",
    # --- UNSUPPORTED in phase 1 (extension path only) ---
    # "lurie-coed-general": "EducationRubric.md",
    # "coeng-deans": "EngineeringRubric.md",
    # "physics-dept": "PhysicsRubric.md",
}

# --- Model shortlist (configurable) ---
# inference_type: "profile" -> INFERENCE_PROFILE (invoke id needs "us." prefix)
#                 "on_demand" -> invoke with the plain model id
# `alt` documents the closest enabled substitute when the requested id is absent.
# Availability is verified at runtime; unavailable models are marked and skipped,
# never failing the whole run.
MODELS = [
    {"id": "amazon.nova-micro-v1:0", "label": "Nova Micro", "inference_type": "profile",
     "cost_per_1k_in": 0.000035, "cost_per_1k_out": 0.00014},
    {"id": "amazon.nova-lite-v1:0", "label": "Nova Lite", "inference_type": "profile",
     "cost_per_1k_in": 0.00006, "cost_per_1k_out": 0.00024},
    {"id": "amazon.nova-pro-v1:0", "label": "Nova Pro", "inference_type": "profile",
     "cost_per_1k_in": 0.0008, "cost_per_1k_out": 0.0032},
    {"id": "qwen.qwen3-32b-v1:0", "label": "Qwen3 32B", "inference_type": "on_demand",
     "cost_per_1k_in": 0.0004, "cost_per_1k_out": 0.0004},
    {"id": "anthropic.claude-haiku-4-5-20251001-v1:0", "label": "Claude Haiku 4.5",
     "inference_type": "profile", "cost_per_1k_in": 0.0008, "cost_per_1k_out": 0.004},
    {"id": "openai.gpt-oss-120b-1:0", "label": "GPT-OSS 120B", "inference_type": "on_demand",
     "cost_per_1k_in": 0.0006, "cost_per_1k_out": 0.0024},
]

# If True, when a shortlisted model is unavailable but has an `alt` that IS
# available, evaluate the alt (clearly labeled as a substitution in the report).
USE_ALTERNATES = True


def invoke_id(model: dict) -> str:
    """Return the id used at invoke time. INFERENCE_PROFILE models need 'us.' prefix."""
    mid = model["id"]
    if model.get("inference_type") == "profile" and not mid.startswith("us."):
        return "us." + mid
    return mid
