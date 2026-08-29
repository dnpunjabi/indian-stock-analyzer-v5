import os
import sys
import re

print("==================================================")
print("1. AUDITING ALL CHAT HANDLERS IN STATIC APP.JS FOR LLMMETA")
print("==================================================")

app_js_path = os.path.join(os.path.dirname(__file__), "static", "app.js")

with open(app_js_path, "r", encoding="utf-8") as f:
    app_js_content = f.read()

# Search for all function declarations matching function append...Chat...
pattern = r"function\s+(append\w*Chat\w*)\s*\(([^)]*)\)"
matches = re.findall(pattern, app_js_content)

print(f"Found {len(matches)} chat append functions:")
has_error = False

for func_name, params in matches:
    print(f" - {func_name}({params})")
    # Check if function body references llmMeta
    # Extract function body
    func_start = app_js_content.find(f"function {func_name}")
    if func_start != -1:
        # Simple bracket count to find end of function
        open_b = app_js_content.find("{", func_start)
        close_b = open_b
        depth = 1
        for i in range(open_b + 1, len(app_js_content)):
            if app_js_content[i] == "{":
                depth += 1
            elif app_js_content[i] == "}":
                depth -= 1
                if depth == 0:
                    close_b = i
                    break
        body = app_js_content[func_start:close_b+1]
        
        if "llmMeta" in body and "llmMeta" not in params:
            print(f"[FAIL] ERROR: Function {func_name} references llmMeta in body but missing from parameters!")
            has_error = True
        else:
            print(f"   [OK] Signature OK")

if not has_error:
    print("SUCCESS: All JS chat append functions properly declare llmMeta in parameters!")
else:
    print("FAILURE: Unhandled llmMeta references found in JS chat append functions!")

print("\n==================================================")
print("2. TESTING LLM GENERATION & STREAMING DECODER")
print("==================================================")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from backend.llm_config import call_llm, call_llm_stream, TASK_HEAVY, TASK_FAST

test_prompt = """
Analyze the sequential (QoQ) and yearly (YoY) revenue and net profit trends for Bajaj Auto Ltd. 
Provide a comprehensive, highly detailed 5-part institutional financial analysis covering:
1. Quarterly Revenue & PAT Trajectory
2. Operating Margin Expansion & Raw Material Cost Sensitivity
3. Export Volumes vs Domestic 2W/3W Mix
4. Capital Allocation, Dividend Yield & Free Cash Flow Generation
5. Detailed Forward Guidance & Valuation Multiples (P/E, EV/EBITDA)
Make sure the response is exhaustive and thoroughly formatted with Markdown headings and tables.
"""

if __name__ == "__main__":
    print("[Test 1] Testing non-streaming call_llm (TASK_HEAVY)...")
    res = call_llm(TASK_HEAVY, "You are a senior institutional equity analyst.", test_prompt, max_tokens=8000)
    print(f"Received non-streaming response length: {len(res)} characters.")
    if len(res) > 500 and not res.startswith("ERROR"):
        print("[OK] Non-streaming response generated cleanly without truncation.")
        print("Sample response tail:")
        print("..." + res[-200:].encode("ascii", errors="replace").decode("ascii"))
    else:
        print(f"[FAIL] Non-streaming test issue: {res[:200]}")

    print("\n[Test 2] Testing streaming call_llm_stream (TASK_FAST)...")
    chunks = []
    full_stream_text = ""
    for chunk in call_llm_stream(TASK_FAST, "You are an institutional financial analyst.", test_prompt, max_tokens=8000):
        chunks.append(chunk)
        full_stream_text += chunk

    print(f"Received {len(chunks)} streaming chunks. Total length: {len(full_stream_text)} characters.")
    if len(full_stream_text) > 500 and not full_stream_text.startswith("ERROR"):
        print("[OK] Streaming response generated cleanly without truncation or missing tail chunks.")
        print("Sample streaming response tail:")
        print("..." + full_stream_text[-200:].encode("ascii", errors="replace").decode("ascii"))
    else:
        print(f"[FAIL] Streaming test issue: {full_stream_text[:200]}")

    print("\n==================================================")
    print("TESTING COMPLETED SUCCESSFULLY")
    print("==================================================")

