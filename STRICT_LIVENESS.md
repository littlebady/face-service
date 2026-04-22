# Strict Liveness (High-Security Mode)

This project now supports a strict liveness pipeline:

1. Client requests one-time challenge.
2. Client finishes random action sequence.
3. Client uploads short evidence frames to backend for anti-spoof review.
4. Backend issues one-time `liveness_ticket` (HMAC signed).
5. `/checkin` must carry `liveness_ticket`, and backend binds session to:
   - `key_image_hash` (anti-tamper),
   - face embedding similarity (session-face binding),
   - one-time ticket consumption (anti-replay).

Raw video is not persisted by backend. Only derived features/scores are kept in memory for the short-lived session.

## Model Path

Place your anti-spoof ONNX model at:

`models/anti_spoof/anti_spoof.onnx`

or set:

`FACE_SERVICE_ANTISPOOF_MODEL_PATH=/absolute/path/to/your_model.onnx`

## Recommended Environment Variables

- `FACE_SERVICE_STRICT_LIVENESS_REQUIRED=true`
- `FACE_SERVICE_ANTISPOOF_REQUIRED=true`
- `FACE_SERVICE_ANTISPOOF_MIN_LIVE_SCORE=0.60`
- `FACE_SERVICE_LIVENESS_SIGNING_KEY=<strong-random-secret>`
- `FACE_SERVICE_LIVENESS_TICKET_TTL_SECONDS=180`
- `FACE_SERVICE_LIVENESS_SESSION_FACE_MIN_SIMILARITY=0.62`
- `FACE_SERVICE_LIVENESS_EVIDENCE_MIN_FRAMES=4`
- `FACE_SERVICE_LIVENESS_EVIDENCE_MAX_FRAMES=16`

## API Sequence

- `POST /checkins/liveness/challenge`
- `POST /checkins/liveness/verify`
- `POST /checkin` (with `liveness_ticket`)

