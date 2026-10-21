# GraphHacks Component 1 — Groq Reliability Fix

Applies to the **Step 1 Agent Runtime** release created earlier. Does not modify FalkorDB or the frontend.

## What this addresses

- `JSONDecodeError: Unterminated string...` during initial plan: switched Groq planning requests (no tools) to supported JSON Object mode; increased planning output cap from 550 to 1250 tokens; reduced GPT-OSS reasoning effort to `low`; retries malformed/truncated plans once with a shorter-plan request. For malformed final JSON, the next bounded decision iteration asks the model for a complete JSON response instead of failing the whole run immediately.
- `ProviderError: groq returned HTTP 429`: read `retry-after` response header, retry at most once when its delay fits inside the run's remaining wall-clock deadline. If it cannot wait safely, fail with an explicit rate-limited message, not a fabricated successful result.
- Default Groq model now `openai/gpt-oss-120b` instead of the unavailable `llama-3.3-70b-versatile` on the user's account. Explicit `GRAPH_HACKS_AGENT_MODEL` continues to take precedence.
- GPT-OSS tool calls disable parallel tool requests for compatibility.

This patch does not bypass Groq limits, extend quota, or guarantee every LLM response is correct. The current agent remains read-only and single-agent. It does not change credentials, source adapter connectivity or data.

## Safe local installation (PowerShell)

1. Stop the running Uvicorn backend (`Ctrl+C`).
2. From `G:\graphhacks`, make backups:

```powershell
Copy-Item .\backend\app\agent_runtime\provider.py .\backend\app\agent_runtime\provider.py.before-groq-fix
Copy-Item .\backend\app\agent_runtime\harness.py .\backend\app\agent_runtime\harness.py.before-groq-fix
```

3. Extract **GraphHacks_Component1_Groq_Reliability_Fix.zip** into `G:\graphhacks` (the archive paths start with `backend\...`):

```powershell
Expand-Archive "$HOME\Downloads\GraphHacks_Component1_Groq_Reliability_Fix.zip" -DestinationPath "G:\graphhacks" -Force
```

4. Verify:

```powershell
python -m pytest backend/tests/test_agent_runtime_provider_resilience.py backend/tests/test_agent_runtime_step1.py -q
```

5. Start backend in the **same terminal** where Groq key and Asteria settings are present (set again if needed):

```powershell
$env:GRAPH_HACKS_AGENT_PROVIDER = 'groq'
$env:GRAPH_HACKS_AGENT_MODEL = 'openai/gpt-oss-120b'
$env:FALKORDB_GRAPH = 'asteria_company_brain_v1'
$env:GRAPH_TENANT_ID = 'asteria'
Write-Host 'Groq key present:' ([bool]$env:GROQ_API_KEY)
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Never share the API key. If it is missing, restore it securely before launching the backend.

6. Wait for Groq rate-limit recovery, then run **one** Demo Lab investigation. Use 4 to 6 decision iterations initially, review the persisted trace. If 429 continues, check your organization's remaining TPM/RPD at https://console.groq.com/settings/limits. Avoid repeated clicks while rate-limited.

## Local verification performed during packaging

- 18 focused tests passed (mock transport; no live Groq API calls)
- 459 backend non-integration tests passed; 299 integration tests excluded
- Python source compilation passes

**Not verified here:** live Groq completion, FalkorDB-backed agent run on user's machine, frontend UI/browser. Stop after one run and inspect trace/error before rerunning.
