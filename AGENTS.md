# AGENTS.md

## Response Format
- Always respond with a quick summary first.
- Then provide details.

## WSL Stability Playbook
When WSL commands fail with `Wsl/Service/E_UNEXPECTED`, `Catastrophic failure`, or repeated unexplained timeouts:

1. Run a health check immediately:
   - `wsl --status`
   - `wsl -l -v`
   - `wsl -d Ubuntu-24.04 bash -lc "echo alive && uname -a"`

2. If any check fails or the distro is not healthy, run recovery in this order:
   - `wsl --shutdown`
   - `Restart-Service WSLService`
   - Wait 3 seconds
   - `wsl -d Ubuntu-24.04 bash -lc "echo alive && uname -a && date"`

3. Retry the original command inside WSL paths, not Windows UNC fallbacks.

4. Do not use Windows `npm`/`node` execution against UNC workspace paths.
   - Build/test commands should run in WSL.

5. If recovery fails twice in a row, stop and tell the user to restart their desktop launcher/script, then resume.

## Frontend Validation Rule
- After UI/CSS/interaction changes, validate with Playwright before final response.
- Validation must include:
  - Main/default viewport screenshot.
  - Small window viewport screenshot.
  - Console error check.