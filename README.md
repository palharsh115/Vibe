# Vibe — Stage 3 (real-time anonymous chat)

Stage 3 extends the Stage 2 prototype with real-time WebSocket messaging for users who have been matched. Keep your existing Stage 2 folder backed up before replacing it.

## What works
- Existing account registration/login, adult eligibility check, preferences, consent-based location, and nearby matching remain in place.
- When a match is found, both users enter the same private chat room.
- Messages are sent and received in real time using FastAPI WebSockets.
- Messages are saved in the local database and the latest 100 messages are loaded when a matched user reconnects.
- The API checks that the signed-in user belongs to the active match. Message content is limited to 500 characters and inserted into the page using `textContent`.
- Chat messages do not expose email, exact coordinates, or account IDs to the other user.

## Run on Windows
1. Extract the ZIP and open the `vibe_stage2` folder in VS Code.
2. Open Command Prompt in `vibe_stage2\backend` and run `run_windows.bat`.
3. Keep that terminal open. Check `http://127.0.0.1:8000/health` and `http://127.0.0.1:8000/docs`.
4. Open a second Command Prompt in `vibe_stage2\frontend` and run `py -m http.server 5500 --bind 127.0.0.1`.
5. Visit `http://127.0.0.1:5500`.
6. Use two different test accounts in separate browser sessions. Both must be 18+, opt in to location, choose the same intention, have compatible vibe selections, and be within both selected radii. Click Find my vibe for both accounts.
7. Once matched, send messages from either browser; they should appear in both chat windows.

## Important limitations
- This is a local prototype, not production-ready chat infrastructure. The in-memory WebSocket manager works only in one backend process and does not support multiple server workers.
- For this local MVP, the short-lived bearer token is passed in the WebSocket query string because browser WebSocket APIs do not support custom Authorization headers. Query strings can be logged; before public deployment, replace this with a short-lived, single-use WebSocket ticket and use HTTPS/WSS.
- Message history is currently retained in the local database. Add retention/deletion controls and a user-visible delete-account flow before launch.
- Block/report currently displays a notice only; it does not persist reports or block future matches. Do not launch publicly until block/report, moderation, rate limiting, spam/abuse protection, verification, security review, and privacy/retention policies are implemented.
- Use only test accounts and never reuse an important password. Do not expose the development server directly to the public internet.

## Files changed
- `backend/app/main.py`: chat message model and authenticated WebSocket endpoint.
- `frontend/api.js`: centralized WebSocket connection helper. Existing HTTP `fetch()` calls remain centralized here.
- `frontend/app.js`: real chat rendering, connection lifecycle, and send-message handling.
- `frontend/index.html`: removed fake sample messages and updated chat labels.


## Stage 4 safety controls
- **Report** (`…` button in chat) saves a report against the current match with a reason and optional details.
- **Block user** ends the active match and prevents that pair from being matched again in either direction.
- Reports are stored in the local database for this prototype; there is no moderation dashboard, alerting, or human review queue yet. Do not treat this as production-ready safety infrastructure.
- Existing SQLite databases gain the new `user_blocks` and `user_reports` tables automatically when the API starts.
