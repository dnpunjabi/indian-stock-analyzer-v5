import os
from unittest.mock import patch
from dotenv import load_dotenv
load_dotenv(override=True)

from backend.llm_config import call_llm, TASK_FAST, TASK_HEAVY

print("="*60)
print("TESTING CALL_LLM WITH GEMINI (LOCAL)")
print("="*60)
with patch.dict(os.environ, {"LLM_PROVIDER": "gemini"}):
    res1 = call_llm(TASK_FAST, "Return a short JSON object", "Generate test output")
    print(f"Gemini Fast Output:\n{res1[:200]}\n")

    res2 = call_llm(TASK_HEAVY, "Return a short JSON object", "Generate test output")
    print(f"Gemini Heavy Output:\n{res2[:200]}\n")

print("="*60)
print("TESTING CALL_LLM WITH GROQ (LOCAL)")
print("="*60)
with patch.dict(os.environ, {"LLM_PROVIDER": "groq"}):
    res3 = call_llm(TASK_FAST, "Return a short JSON object", "Generate test output")
    print(f"Groq Fast Output:\n{res3[:200]}\n")

    res4 = call_llm(TASK_HEAVY, "Return a short JSON object", "Generate test output")
    print(f"Groq Heavy Output:\n{res4[:200]}\n")
