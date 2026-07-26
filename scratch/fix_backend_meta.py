"""
Add llm_meta to all backend API endpoint responses in main.py.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('backend/main.py', 'r', encoding='utf-8') as f:
    content = f.read()

changes = 0

# First, ensure the import is at the top level (it's already imported at L49)
# from backend.llm_config import get_last_llm_meta

# 1. /api/chat - advisory_chat (L5580)
old = 'return {"response": clean_response, "actions": actions}'
new = 'return {"response": clean_response, "actions": actions, "llm_meta": get_last_llm_meta()}'
if old in content and 'llm_meta' not in content[content.index(old):content.index(old)+len(old)+20]:
    content = content.replace(old, new, 1)
    changes += 1
    print(f'[{changes}] /api/chat')

# 2. /api/chart/chat-analyst (L4579) 
old = 'return {"analysis": analysis}'
new = 'return {"analysis": analysis, "llm_meta": get_last_llm_meta()}'
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print(f'[{changes}] /api/chart/chat-analyst')

# 3. /api/chart/indicator-synthesis (L4324-4328)
old = '''return {
            "symbol": ticker,
            "indicator": indicator,
            "synthesis": synthesis
        }'''
new = '''return {
            "symbol": ticker,
            "indicator": indicator,
            "synthesis": synthesis,
            "llm_meta": get_last_llm_meta()
        }'''
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print(f'[{changes}] /api/chart/indicator-synthesis')

# 4. /api/analyze/risk-synthesis (L10102)
old = '''synthesis = await asyncio.to_thread(call_llm, TASK_FAST, system_prompt, user_prompt)
        return {"synthesis": synthesis}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Risk Synthesis Error: {str(e)}")'''
new = '''synthesis = await asyncio.to_thread(call_llm, TASK_FAST, system_prompt, user_prompt)
        return {"synthesis": synthesis, "llm_meta": get_last_llm_meta()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Risk Synthesis Error: {str(e)}")'''
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print(f'[{changes}] /api/analyze/risk-synthesis')

# 5. /api/portfolio/backtest-synthesis (L10218)
old = '''synthesis = await asyncio.to_thread(
            generate_backtest_synthesis,
            metrics=data.metrics,
            tickers_weights=data.tickers_weights
        )
        return {"synthesis": synthesis}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backtest Synthesis Error: {str(e)}")'''
new = '''synthesis = await asyncio.to_thread(
            generate_backtest_synthesis,
            metrics=data.metrics,
            tickers_weights=data.tickers_weights
        )
        return {"synthesis": synthesis, "llm_meta": get_last_llm_meta()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backtest Synthesis Error: {str(e)}")'''
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print(f'[{changes}] /api/portfolio/backtest-synthesis')

# 6. /api/portfolio/optimizer-synthesis (L10552)
old = '''synthesis = await asyncio.to_thread(call_llm, TASK_FAST, system_prompt, user_prompt)
        return {"synthesis": synthesis}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Optimizer Synthesis Error: {str(e)}")'''
new = '''synthesis = await asyncio.to_thread(call_llm, TASK_FAST, system_prompt, user_prompt)
        return {"synthesis": synthesis, "llm_meta": get_last_llm_meta()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Optimizer Synthesis Error: {str(e)}")'''
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print(f'[{changes}] /api/portfolio/optimizer-synthesis')

# 7. /api/screener/explain-formula (L13634)
old = 'return {"status": "success", "explanation": explanation.strip()}'
new = 'return {"status": "success", "explanation": explanation.strip(), "llm_meta": get_last_llm_meta()}'
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print(f'[{changes}] /api/screener/explain-formula')

# 8. /api/screener/scan-synthesis (L13607)
old = 'return {"status": "success", "synthesis": summary.strip()}'
new = 'return {"status": "success", "synthesis": summary.strip(), "llm_meta": get_last_llm_meta()}'
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print(f'[{changes}] /api/screener/scan-synthesis')

# 9. /api/swing/synthesis (L11941)
old = '''synthesis = f"{p1}\\n\\n{p2}\\n\\n{p3}\\n\\n{p4}"
            
        return {"synthesis": synthesis}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Swing trade synthesis failed: {str(e)}")'''
new = '''synthesis = f"{p1}\\n\\n{p2}\\n\\n{p3}\\n\\n{p4}"
            
        return {"synthesis": synthesis, "llm_meta": get_last_llm_meta()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Swing trade synthesis failed: {str(e)}")'''
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print(f'[{changes}] /api/swing/synthesis')

# 10. /api/screener/sector-regime/ai-analysis (L3402) 
# This returns a parsed JSON dict from LLM response
old = '''        for s in sector_standings:
            sec_name = s["sector"]
            if sec_name not in result["sector_sentiments"]:
                ret_val = s[f"return_{period}"]
                if ret_val >= 5.0: score = 85
                elif ret_val >= 0.0: score = 65
                elif ret_val >= -5.0: score = 42
                else: score = 20
                result["sector_sentiments"][sec_name] = score
        return result'''
new = '''        for s in sector_standings:
            sec_name = s["sector"]
            if sec_name not in result["sector_sentiments"]:
                ret_val = s[f"return_{period}"]
                if ret_val >= 5.0: score = 85
                elif ret_val >= 0.0: score = 65
                elif ret_val >= -5.0: score = 42
                else: score = 20
                result["sector_sentiments"][sec_name] = score
        result["llm_meta"] = get_last_llm_meta()
        return result'''
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print(f'[{changes}] /api/screener/sector-regime/ai-analysis')

# 11. /api/portfolio-doctor (L10173)
# This returns the result of run_portfolio_doctor which is a complex dict
# We need to add llm_meta after the call
old = '''        diagnosis = await asyncio.to_thread(run_portfolio_doctor, portfolio_items)
        return diagnosis'''
new = '''        diagnosis = await asyncio.to_thread(run_portfolio_doctor, portfolio_items)
        diagnosis["llm_meta"] = get_last_llm_meta()
        return diagnosis'''
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print(f'[{changes}] /api/portfolio-doctor')

# 12. /api/analyze/pitchbook
# Need to find exact return
old = 'return {"pitchbook_html": pitchbook_html}'
new = 'return {"pitchbook_html": pitchbook_html, "llm_meta": get_last_llm_meta()}'
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print(f'[{changes}] /api/analyze/pitchbook')

# Write the updated content
with open('backend/main.py', 'w', encoding='utf-8') as f:
    f.write(content)

print(f'\n=== TOTAL CHANGES: {changes} ===')
